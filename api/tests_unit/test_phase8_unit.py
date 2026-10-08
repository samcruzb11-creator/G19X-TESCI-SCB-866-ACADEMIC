"""Systemic checks supplement the phase-specific contract suites."""
import re
import asyncio
from io import BytesIO
import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.storage_service import StorageService


def test_every_private_operation_requires_authentication():
    public = {'/api/v1/auth/login', '/api/v1/auth/access-requests',
              '/api/v1/auth/password-reset/request', '/api/v1/auth/password-reset/confirm',
              '/api/v1/auth/initial-password/confirm', '/'}
    examined = []
    with TestClient(app, raise_server_exceptions=False) as client:
        for template, operations in app.openapi()['paths'].items():
            if template in public:
                continue
            path = re.sub(r'\{[^}]+\}', '1', template)
            for method in operations:
                if method not in {'get', 'post', 'patch', 'delete', 'put'}:
                    continue
                result = client.request(method, path, json={} if method != 'get' else None)
                assert result.status_code == 401, (method, path, result.status_code, result.text)
                examined.append((method, template))
    assert len(examined) >= 40


@pytest.mark.parametrize('key', ['../outside', '..\\outside', '/absolute', 'C:/absolute',
    '//server/share', '%2e%2e/outside', 'documents/%2foutside', 'documents/null\x00', 'documents/../outside'])
def test_storage_rejects_unsafe_keys_before_io(tmp_path, key):
    storage = StorageService(tmp_path/'storage')
    with pytest.raises(ValueError):
        storage.get_absolute_path(key)
    assert not storage.base_path.exists()


def test_database_admission_bounds_workers_and_releases_cancelled_waiters():
    from app.services.database_admission import DatabaseAdmissionMiddleware
    async def exercise():
        active = maximum = 0
        release = asyncio.Event()
        async def application(scope, receive, send):
            nonlocal active, maximum
            active += 1; maximum = max(maximum, active)
            try:
                await release.wait()
            finally:
                active -= 1
        middleware=DatabaseAdmissionMiddleware(application,capacity=2,prefix='/api/v1')
        async def noop(*args):pass
        tasks=[asyncio.create_task(middleware(dict(type='http',path='/api/v1/documentos'),noop,noop)) for _ in range(25)]
        await asyncio.sleep(.01)
        assert active==maximum==2
        tasks[-1].cancel()
        await asyncio.gather(tasks[-1],return_exceptions=True)
        release.set()
        await asyncio.gather(*tasks[:-1])
        assert active==0 and maximum==2
        assert middleware.gates[asyncio.get_running_loop()][1]==0
    asyncio.run(exercise())


def test_database_admission_queue_is_bounded_and_overload_is_sanitized():
    from app.services.database_admission import DatabaseAdmissionMiddleware
    async def exercise():
        release=asyncio.Event();messages=[]
        async def application(scope, receive, send):await release.wait()
        async def receive():return {'type':'http.disconnect'}
        async def send(message):messages.append(message)
        middleware=DatabaseAdmissionMiddleware(application,capacity=1,prefix='/api/v1')
        tasks=[asyncio.create_task(middleware(dict(type='http',path='/api/v1/auth/me'),receive,send)) for _ in range(258)]
        await asyncio.sleep(.01)
        assert next(m for m in messages if m['type']=='http.response.start')['status']==503
        release.set();await asyncio.gather(*tasks)
        assert middleware.gates[asyncio.get_running_loop()][1]==0
    asyncio.run(exercise())


def test_incomplete_uploads_do_not_reserve_database_admission():
    async def exercise():
        entered = 0
        all_started = asyncio.Event()
        never_finished = asyncio.Event()
        messages = []
        async def receive():
            nonlocal entered
            entered += 1
            if entered == 15:
                all_started.set()
            await never_finished.wait()
            return {'type': 'http.disconnect'}
        async def send(message):
            messages.append(message)
        def scope(method, path, headers):
            return dict(type='http', asgi={'version': '3.0'}, http_version='1.1',
                method=method, scheme='http', path=path, raw_path=path.encode(),
                query_string=b'', root_path='', headers=headers,
                server=('testserver', 80), client=('127.0.0.1', 1234))
        upload = scope('POST', '/api/v1/documentos/1/versiones',
                       [(b'content-type', b'multipart/form-data; boundary=slow')])
        tasks = [asyncio.create_task(app(upload, receive, send)) for _ in range(15)]
        try:
            await asyncio.wait_for(all_started.wait(), 1)
            async def empty():
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            await asyncio.wait_for(app(scope('GET', '/api/v1/auth/me', []), empty, send), 1)
            assert any(m.get('status') == 401 for m in messages)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(exercise())


def test_chunked_multipart_limit_closes_partial_files(monkeypatch):
    from fastapi import FastAPI, UploadFile
    from starlette import formparsers
    from app.core.config import settings
    from app.services.request_body_limit import RequestBodyLimitMiddleware
    monkeypatch.setattr(settings, 'max_document_file_bytes', 16)
    opened = []
    spool = formparsers.SpooledTemporaryFile
    def tracked_spool(*args, **kwargs):
        result = spool(*args, **kwargs)
        opened.append(result)
        return result
    monkeypatch.setattr(formparsers, 'SpooledTemporaryFile', tracked_spool)
    application = FastAPI()
    @application.post('/api/v1/documentos/1/versiones')
    async def upload(archivo: UploadFile):
        pytest.fail('The oversized multipart must not reach the handler')
    application.add_middleware(RequestBodyLimitMiddleware)
    async def exercise():
        parts = iter([
            b'--test\r\nContent-Disposition: form-data; name="archivo"; filename="test.bin"\r\n'
            b'Content-Type: application/octet-stream\r\n\r\n' + b'x' * (128 * 1024 - 200),
            b'x' * 1000 + b'\r\n--test--\r\n'])
        messages = []
        async def receive():
            return {'type': 'http.request', 'body': next(parts), 'more_body': True}
        async def send(message):
            messages.append(message)
        await application(dict(type='http', asgi={'version': '3.0'}, http_version='1.1',
            method='POST', scheme='http', path='/api/v1/documentos/1/versiones',
            query_string=b'', root_path='', headers=[(b'content-type', b'multipart/form-data; boundary=test')],
            server=('testserver', 80), client=('127.0.0.1', 1234)), receive, send)
        assert next(m for m in messages if m['type'] == 'http.response.start')['status'] == 400
        assert opened and all(file.closed for file in opened)
    asyncio.run(exercise())


def test_storage_collision_preserves_existing_file(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module('app.services.storage_service')
    class FixedUUID:
        hex = 'a' * 32
    monkeypatch.setattr(module, 'uuid4', lambda: FixedUUID())
    storage = StorageService(tmp_path / 'storage')
    original = storage.save_file(BytesIO(b'original'), 'same.txt')
    with pytest.raises(FileExistsError):
        storage.save_file(BytesIO(b'replacement'), 'same.txt')
    assert storage.get_absolute_path(original.storage_key).read_bytes() == b'original'
    assert not list(storage.base_path.rglob('*.tmp_*'))


def test_storage_temporary_collision_preserves_other_writer(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module('app.services.storage_service')
    class FixedUUID:
        hex = 'b' * 32
    monkeypatch.setattr(module, 'uuid4', lambda: FixedUUID())
    storage = StorageService(tmp_path / 'storage')
    _, target = storage._build_target_path('documents', '.txt')
    temporary = target.with_suffix('.txt.tmp_' + FixedUUID.hex)
    temporary.write_bytes(b'other writer')
    with pytest.raises(FileExistsError):
        storage.save_file(BytesIO(b'collision'), 'same.txt')
    assert temporary.read_bytes() == b'other writer'
    assert not target.exists()


def test_storage_long_extension_respects_filesystem_limits(tmp_path):
    storage = StorageService(tmp_path / 'storage')
    if os.name == 'nt':
        with pytest.raises(ValueError):
            storage.save_file(BytesIO(b'complete'), 'long.' + 't' * 185)
        assert not storage.base_path.exists()
    else:
        info = storage.save_file(BytesIO(b'complete'), 'long.' + 't' * 185)
        assert storage.get_absolute_path(info.storage_key).read_bytes() == b'complete'
    assert not list(storage.base_path.rglob('*.tmp_*'))


@pytest.mark.skipif(os.name != 'nt', reason='Win32 uses UTF-16 path units')
def test_storage_windows_path_limit_counts_utf16_units(tmp_path):
    extension = '.' + '\U0001f600' * 40
    suffix = '/documents/2026/10/' + 'a' * 32 + extension + '.tmp_' + 'b' * 32
    extra = 245 - len(str(tmp_path)) - len(suffix) - 1
    assert extra > 0
    storage = StorageService(tmp_path / ('a' * extra))
    temporary = str(storage.base_path) + suffix
    assert len(temporary) < 260 <= len(temporary.encode('utf-16-le')) // 2
    with pytest.raises(ValueError):
        storage.save_file(BytesIO(b'complete'), 'test' + extension)
    assert not storage.base_path.exists()


@pytest.mark.parametrize('inside', [False, True])
def test_storage_directory_link_cannot_redirect_reads_or_cleanup(tmp_path, inside):
    storage = StorageService(tmp_path / 'storage')
    parent = storage.base_path / 'documents'
    parent.mkdir(parents=True)
    target = storage.base_path / 'other' if inside else tmp_path / 'outside'
    target.mkdir()
    protected = target / 'synthetic.bin'
    protected.write_bytes(b'untouched')
    link = parent / 'linked'
    if os.name == 'nt':
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        result = subprocess.run(['powershell', '-NoProfile', '-Command',
            'New-Item -ItemType Junction -Path ' + quote(link) + ' -Target ' + quote(target)],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)
    key = 'documents/linked/synthetic.bin'
    with pytest.raises(ValueError):
        storage.get_absolute_path(key)
    assert not storage.delete_file(key)
    assert protected.read_bytes() == b'untouched'
