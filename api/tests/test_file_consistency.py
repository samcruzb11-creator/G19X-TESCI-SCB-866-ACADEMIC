"""MySQL integration tests. conftest refuses the official database before collection."""
import io
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError

from app.models.entities import Area, Auditoria, Documento, EventoAuditoria, Evidencia, Usuario, VersionDocumento
from app.services.documento_service import DocumentoService
from app.services.evidencia_service import EvidenciaService
from app.services.file_transaction import CommitOutcomeUnknown
from app.services.storage_integrity import read_references, scan_storage
from app.services.storage_service import StorageService


@pytest.fixture
def records(db_session_factory):
    """Unique test-only records; cleanup deletes only this fixture's identifiers."""
    suffix = uuid4().hex
    with db_session_factory() as db:
        user = Usuario(nombre="Consistency test", correo=suffix+"@example.invalid", correo_normalizado=suffix+"@example.invalid", password_hash="test-only", rol="AUDITOR_INTERNO")
        area = Area(codigo=suffix, nombre="Test")
        db.add_all([user, area]); db.flush()
        doc = Documento(codigo=suffix, titulo="Test", tipo="TEST", area_id=area.id, responsable_id=user.id, created_by_id=user.id)
        audit = Auditoria(codigo=suffix, nombre="Test", alcance="Isolated test", responsable_id=user.id, created_by_id=user.id)
        db.add_all([doc, audit]); db.flush()
        ids = dict(user=user.id, area=area.id, doc=doc.id, audit=audit.id)
        db.commit()
    yield ids
    with db_session_factory() as db:
        db.execute(update(Documento).where(Documento.id == ids['doc']).values(version_vigente_id=None))
        db.execute(delete(EventoAuditoria).where(EventoAuditoria.actor_id == ids['user']))
        db.execute(delete(Evidencia).where(Evidencia.auditoria_id == ids['audit']))
        db.execute(delete(VersionDocumento).where(VersionDocumento.documento_id == ids['doc']))
        db.execute(delete(Documento).where(Documento.id == ids['doc']))
        db.execute(delete(Auditoria).where(Auditoria.id == ids['audit']))
        db.execute(delete(Area).where(Area.id == ids['area']))
        db.execute(delete(Usuario).where(Usuario.id == ids['user']))
        db.commit()


@pytest.fixture(params=['version', 'evidence'])
def upload_case(request, records, tmp_path, db_session_factory):
    storage = StorageService(tmp_path)
    def upload(db, stream=None):
        stream = stream if stream is not None else io.BytesIO(b'original data')
        if request.param == 'version':
            return DocumentoService(storage).crear_version_documento(db, records['doc'], stream, 'test.pdf', records['user'])
        return EvidenciaService(storage).registrar_evidencia_archivo(db, records['audit'], 'Evidence test', records['user'], stream, 'test.pdf')
    def rows(db):
        if request.param == 'version':
            return list(db.scalars(select(VersionDocumento).where(VersionDocumento.documento_id == records['doc'])))
        return list(db.scalars(select(Evidencia).where(Evidencia.auditoria_id == records['audit'])))
    return storage, upload, rows


@pytest.mark.parametrize('failure', ['stream', 'flush', 'event_flush', 'commit_rejected', 'post_commit', 'unknown_before', 'unknown_after', 'none'])
def test_transaction_boundaries(failure, upload_case, records, db_session_factory, monkeypatch):
    storage, upload, rows = upload_case
    sentinel = storage.save_file(io.BytesIO(b'untouched'), 'sentinel.txt')
    with db_session_factory() as db, monkeypatch.context() as patcher:
        original_commit = db.commit
        stream = None
        if failure == 'stream':
            class Broken(io.BytesIO):
                def read(self, size=-1):
                    if self.tell():
                        raise OSError('stream failure')
                    return super().read(1)
            stream = Broken(b'partial')
        elif failure == 'flush':
            patcher.setattr(db, 'flush', lambda: (_ for _ in ()).throw(RuntimeError('flush failure')))
        elif failure == 'event_flush':
            original_flush = db.flush
            def fail_event(*args, **kwargs):
                if any(isinstance(row, EventoAuditoria) for row in db.new):
                    raise RuntimeError('event flush failure')
                return original_flush(*args, **kwargs)
            patcher.setattr(db, 'flush', fail_event)
        elif failure == 'commit_rejected':
            def reject():
                # A server-side 1213 means transaction rollback. Reproduce that
                # state before raising the driver response, without sending COMMIT.
                db.rollback()
                raise OperationalError(None, None, Exception(1213, 'deadlock'))
            patcher.setattr(db, 'commit', reject)
        elif failure == 'post_commit':
            patcher.setattr(db, 'refresh', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('refresh failure')))
        elif failure.startswith('unknown'):
            def uncertain():
                if failure == 'unknown_after':
                    original_commit()
                raise OSError('connection lost')
            patcher.setattr(db, 'commit', uncertain)
        if failure == 'none':
            upload(db)
        else:
            with pytest.raises((OSError, RuntimeError, OperationalError)):
                upload(db, stream)

    persisted = failure in {'post_commit', 'unknown_after', 'none'}
    retained = failure in {'post_commit', 'unknown_before', 'unknown_after', 'none'}
    with db_session_factory() as db:
        saved = rows(db)
        assert len(saved) == int(persisted)
        events = list(db.scalars(select(EventoAuditoria).where(EventoAuditoria.actor_id == records['user'])))
        assert len(events) == int(persisted)
        for row in saved:
            assert storage.verify_file_integrity(row.storage_key, row.sha256)
    physical = [p for p in storage.base_path.rglob('*') if p.is_file()]
    assert len(physical) == 1 + int(retained)
    assert Path(sentinel.absolute_path).read_bytes() == b'untouched'


def test_verifier_reads_real_test_metadata(upload_case, db_session_factory):
    storage, upload, rows = upload_case
    with db_session_factory() as db:
        row = upload(db)
        key = row.storage_key
        entity = 'version' if isinstance(row, VersionDocumento) else 'evidence'
        row_id = row.id
    with db_session_factory() as db:
        references = [r for r in read_references(db) if (r.entity, r.id) == (entity, row_id)]
    assert scan_storage(references, storage.base_path).exit_code == 0
    path = storage.get_absolute_path(key)
    path.write_bytes(b'changed length and content')
    report = scan_storage(references, storage.base_path)
    assert report.counts == {'hash_mismatch': 1, 'size_mismatch': 1}
    path.unlink()  # This is only the test's temporary storage.
    assert scan_storage(references, storage.base_path).counts == {'missing_file': 1}
    orphan = storage.save_file(io.BytesIO(b'orphan'), 'orphan.pdf')
    assert scan_storage([], storage.base_path).counts == {'orphan_candidate': 1}
    assert Path(orphan.absolute_path).read_bytes() == b'orphan'
