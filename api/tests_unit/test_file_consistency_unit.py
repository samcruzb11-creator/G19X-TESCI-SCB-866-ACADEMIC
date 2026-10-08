"""No database connections: failure-boundary and read-only scanner unit tests."""
import hashlib
import io
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.models.entities import Auditoria, Documento, Evidencia, Usuario, VersionDocumento
from app.models.entities import EventoAuditoria
from app.services.documento_service import DocumentoService
from app.services.evidencia_service import EvidenciaService
from app.services.file_transaction import CommitOutcomeUnknown
from app.services.storage_integrity import FileReference, scan_storage
from app.services.storage_service import StorageService


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real database connections forbidden in unit tests")
    monkeypatch.setattr(Engine, "connect", forbidden)


@pytest.fixture(params=["version", "evidence"])
def operation(request, tmp_path):
    storage = StorageService(tmp_path)
    actor = Usuario(id=1, nombre="Test", correo="test@example.invalid", rol="ADMIN", activo=True)
    doc = Documento(id=1, estado="DRAFT")
    audit = Auditoria(id=1, estado="PLANNED")
    db = Mock()
    db.get.side_effect = lambda model, id: actor if model is Usuario else audit if model is Auditoria else doc
    def scalar(statement):
        entity = statement.column_descriptions[0].get('entity')
        return actor if entity is Usuario else audit if entity is Auditoria else doc if entity is Documento else 0
    db.scalar.side_effect = scalar
    pending, persisted = [], []
    db.add.side_effect = pending.append

    def flush():
        for item in pending:
            item.id = item.id or len(pending)
            if hasattr(item, "created_at"):
                item.created_at = datetime(2026, 1, 1)
    db.flush.side_effect = flush
    db.commit.side_effect = lambda: persisted.extend(pending)

    def upload(stream=None):
        stream = stream if stream is not None else io.BytesIO(b"content")
        if request.param == "version":
            return DocumentoService(storage).crear_version_documento(db, 1, stream, "test.pdf", 1)
        return EvidenciaService(storage).registrar_evidencia_archivo(db, 1, "Test evidence", 1, stream, "test.pdf")
    return db, storage, upload, persisted


def files(storage):
    return [p for p in storage.base_path.rglob("*") if p.is_file()]


def test_a_stream_failure(operation):
    db, storage, upload, persisted = operation
    class Broken(io.BytesIO):
        calls = 0
        def read(self, n=-1):
            self.calls += 1
            if self.calls > 1:
                raise OSError("simulated streaming failure")
            return b"partial"
    with pytest.raises(OSError):
        upload(Broken())
    assert not files(storage) and not persisted
    db.add.assert_not_called()
    db.rollback.assert_called_once()


def test_b_flush_failure_only_removes_new_file(operation):
    db, storage, upload, persisted = operation
    unrelated = storage.save_file(io.BytesIO(b"old"), "old.pdf")
    db.flush.side_effect = RuntimeError("flush failed")
    with pytest.raises(RuntimeError, match="flush failed"):
        upload()
    assert files(storage) == [Path(unrelated.absolute_path)]
    assert not persisted
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_c_commit_explicitly_rejected(operation):
    db, storage, upload, persisted = operation
    db.commit.side_effect = OperationalError(None, None, Exception(1213, "deadlock"))
    with pytest.raises(OperationalError):
        upload()
    assert not files(storage) and not persisted
    db.rollback.assert_called_once()


def test_d_successful_commit_then_refresh_failure(operation):
    db, storage, upload, persisted = operation
    db.refresh.side_effect = RuntimeError("refresh unavailable")
    with pytest.raises(RuntimeError, match="refresh unavailable"):
        upload()
    assert len(files(storage)) == 1
    assert any(isinstance(row, (VersionDocumento, Evidencia)) for row in persisted)
    db.rollback.assert_not_called()


@pytest.mark.parametrize("server_committed", [False, True])
def test_uncertain_commit_never_deletes_or_retries(operation, server_committed):
    db, storage, upload, persisted = operation
    real_commit = db.commit.side_effect
    def uncertain():
        if server_committed:
            real_commit()
        raise OSError("connection lost")
    db.commit.side_effect = uncertain
    with pytest.raises(CommitOutcomeUnknown):
        upload()
    assert len(files(storage)) == 1
    assert bool(persisted) is server_committed
    db.commit.assert_called_once()
    db.refresh.assert_not_called()


def test_cleanup_failure_does_not_hide_original_error(operation, monkeypatch):
    db, storage, upload, _ = operation
    db.flush.side_effect = RuntimeError("original flush failure")
    monkeypatch.setattr(storage, "delete_file", Mock(side_effect=OSError("denied")))
    with pytest.raises(RuntimeError, match="original flush failure"):
        upload()
    assert len(files(storage)) == 1


def test_event_flush_failure_is_still_pre_commit(operation):
    db, storage, upload, persisted = operation
    original_flush = db.flush.side_effect
    def fail_event():
        original_flush()
        if any(isinstance(call.args[0], EventoAuditoria) for call in db.add.call_args_list):
            raise RuntimeError('event flush failed')
    db.flush.side_effect = fail_event
    with pytest.raises(RuntimeError, match='event flush failed'):
        upload()
    db.commit.assert_not_called()
    assert not files(storage) and not persisted


def test_failed_rollback_retains_file_for_reconciliation(operation):
    db, storage, upload, _ = operation
    db.flush.side_effect = RuntimeError('original failure')
    db.rollback.side_effect = OSError('disconnected')
    with pytest.raises(RuntimeError, match='original failure'):
        upload()
    assert len(files(storage)) == 1
    db.commit.assert_not_called()


def test_e_orphan_is_reported_without_changes(tmp_path):
    storage = StorageService(tmp_path)
    file = storage.save_file(io.BytesIO(b"orphan"), "orphan.pdf")
    before = Path(file.absolute_path).stat()
    report = scan_storage([], tmp_path)
    assert report.counts == {"orphan_candidate": 1} and report.exit_code == 1
    after = Path(file.absolute_path).stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert Path(file.absolute_path).read_bytes() == b"orphan"


def test_f_missing_file(tmp_path):
    report = scan_storage([FileReference("version", 1, "documents/missing.pdf", "a"*64, 1)], tmp_path)
    assert report.counts == {"missing_file": 1} and report.exit_code == 1


def test_g_hash_and_size_mismatch(tmp_path):
    storage = StorageService(tmp_path)
    file = storage.save_file(io.BytesIO(b"original"), "file.pdf")
    ref = FileReference("evidence", 1, file.storage_key, file.sha256, file.tamano_bytes)
    assert scan_storage([ref], tmp_path).exit_code == 0
    Path(file.absolute_path).write_bytes(b"modified and larger")
    report = scan_storage([ref], tmp_path)
    assert report.counts == {"hash_mismatch": 1, "size_mismatch": 1}
    assert Path(file.absolute_path).read_bytes() == b"modified and larger"


@pytest.mark.parametrize("key", ["../escape", "documents/../../escape", r"..\escape", "/absolute", "C:/secret", r"C:\secret"])
def test_h_traversal(tmp_path, key):
    with pytest.raises(ValueError):
        StorageService(tmp_path).get_absolute_path(key)
    report = scan_storage([FileReference("version", 1, key, "a"*64, 1)], tmp_path)
    assert report.counts == {"invalid_storage_key": 1}
    assert "key" not in report.issues[0]


def test_temporaries_are_reported_never_removed(tmp_path):
    folder = tmp_path / "documents"
    folder.mkdir()
    old = folder / "file.pdf.tmp_old"
    recent = folder / ".tmp_recent"
    old.write_bytes(b"old"); recent.write_bytes(b"new")
    os.utime(old, (0, 0))
    report = scan_storage([], tmp_path)
    assert report.counts == {"temporary_abandoned_candidate": 1, "temporary_recent": 1}
    assert old.exists() and recent.exists()


def test_missing_root_is_not_created(tmp_path):
    root = tmp_path / "does-not-exist"
    report = scan_storage([], root)
    assert report.exit_code == 2 and not root.exists()


def test_post_commit_serialization_failure(operation):
    db, storage, upload, persisted = operation
    row = upload()
    with pytest.raises(RuntimeError):
        raise RuntimeError("response encoding failed")
    assert row in persisted and len(files(storage)) == 1
    db.rollback.assert_not_called()
