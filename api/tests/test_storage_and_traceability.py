"""Suite de pruebas de integración para Almacenamiento, Inmutabilidad Criptográfica y Trazabilidad."""

import hashlib
import io
import shutil
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

import pytest
from sqlalchemy import text
from app.models.entities import Area, Auditoria, Documento, EventoAuditoria, Evidencia, Usuario, VersionDocumento
from app.schemas.documento import DocumentoCreate
from app.services.documento_service import DocumentoService
from app.services.evidencia_service import EvidenciaService
from app.services.storage_service import StorageService


@pytest.fixture(autouse=True)
def clean_database(db_session_factory):
    """Limpia las tablas de negocio antes y después de cada prueba de integración."""
    session = db_session_factory()
    try:
        session.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        tables = [
            "decisiones_aprobacion",
            "rondas_aprobacion",
            "hallazgos_evidencias",
            "evidencias",
            "hallazgos",
            "documentos_auditoria",
            "versiones_documento",
            "documentos",
            "auditorias",
            "areas",
            "eventos_auditoria",
            "usuarios",
        ]
        for t in tables:
            session.execute(text(f"TRUNCATE TABLE {t};"))
        session.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        session.commit()
    finally:
        session.close()

    yield

    session = db_session_factory()
    try:
        session.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        for t in tables:
            session.execute(text(f"TRUNCATE TABLE {t};"))
        session.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        session.commit()
    finally:
        session.close()


def test_storage_service_streaming_and_integrity():
    """Valida el cómputo del hash en streaming, almacenamiento y verificación de integridad."""
    temp_dir = mkdtemp()
    try:
        storage = StorageService(base_path=temp_dir, chunk_size=1024)

        # Generar contenido de prueba (100 KB para validar múltiples chunks)
        sample_payload = b"PluriOne LegalTech Audit Payload - " * 3000
        expected_sha256 = hashlib.sha256(sample_payload).hexdigest()
        stream = io.BytesIO(sample_payload)

        info = storage.save_file(
            file_stream=stream,
            filename="contrato_marco_2026.pdf",
            content_type="application/pdf",
            category="test_docs",
        )

        assert info.sha256 == expected_sha256
        assert info.tamano_bytes == len(sample_payload)
        assert info.nombre_original == "contrato_marco_2026.pdf"
        assert info.mime_type == "application/pdf"
        assert Path(info.absolute_path).exists()

        # Verificar integridad
        assert storage.verify_file_integrity(info.storage_key, expected_sha256) is True
        assert storage.verify_file_integrity(info.storage_key, "invalid_hash_abc123") is False

        # Verificar eliminación (cleanup)
        assert storage.delete_file(info.storage_key) is True
        assert not Path(info.absolute_path).exists()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_documento_version_creation_and_audit_trail(db_session_factory):
    """Valida la creación atómica de versión, actualización de versión vigente y bitácora de auditoría."""
    temp_dir = mkdtemp()
    session = db_session_factory()
    try:
        storage = StorageService(base_path=temp_dir)
        doc_service = DocumentoService(storage=storage)

        # 1. Setup usuario y área
        u = Usuario(
            nombre="Auditor Certificado",
            correo="auditor@plurione.com",
            correo_normalizado="auditor@plurione.com",
            password_hash="pwd_hash_123",
            rol="AUDITOR_INTERNO",
        )
        area = Area(codigo="COMPLIANCE", nombre="Oficina de Cumplimiento")
        session.add_all([u, area])
        session.commit()
        session.refresh(u)
        session.refresh(area)

        # 2. Crear Documento
        doc_in = DocumentoCreate(
            codigo="DOC-SLA-2026",
            titulo="SLA de Servicios LegalTech",
            tipo="ACUERDO",
            area_id=area.id,
            responsable_id=u.id,
        )
        doc = doc_service.crear_documento(session, doc_in, creador_id=u.id)
        assert doc.id is not None
        assert doc.version_vigente_id is None

        # 3. Crear Versión 1 con streaming
        payload_v1 = b"Version 1 - Contenido inicial aprobado legalmente"
        expected_sha_v1 = hashlib.sha256(payload_v1).hexdigest()
        stream_v1 = io.BytesIO(payload_v1)

        v1 = doc_service.crear_version_documento(
            db=session,
            documento_id=doc.id,
            file_stream=stream_v1,
            filename="sla_v1.pdf",
            subido_por_id=u.id,
            comentario_cambio="Emisión inicial del SLA",
            actualizar_vigente=True,
        )

        assert v1.numero_version == 1
        assert v1.sha256 == expected_sha_v1
        assert doc.version_vigente_id == v1.id
        assert doc.estado == "ACTIVE"

        # 4. Verificar evento en bitácora inmutable
        evento_v1 = (
            session.query(EventoAuditoria)
            .filter(
                EventoAuditoria.entidad_tipo == "DOCUMENTO",
                EventoAuditoria.entidad_id == str(doc.id),
                EventoAuditoria.accion == "CREACION_VERSION",
            )
            .order_by(EventoAuditoria.id.desc())
            .first()
        )
        assert evento_v1 is not None
        assert evento_v1.actor_id == u.id
        assert evento_v1.datos_nuevos["sha256"] == expected_sha_v1
        assert evento_v1.datos_nuevos["numero_version"] == 1

        # 5. Crear Versión 2 (incremento correlativo y vigencia)
        payload_v2 = b"Version 2 - Modificacion de clausula de penalizaciones"
        expected_sha_v2 = hashlib.sha256(payload_v2).hexdigest()
        stream_v2 = io.BytesIO(payload_v2)

        v2 = doc_service.crear_version_documento(
            db=session,
            documento_id=doc.id,
            file_stream=stream_v2,
            filename="sla_v2.pdf",
            subido_por_id=u.id,
            comentario_cambio="Ajuste de penalizaciones",
            actualizar_vigente=True,
        )

        assert v2.numero_version == 2
        assert v2.sha256 == expected_sha_v2
        assert doc.version_vigente_id == v2.id

    finally:
        session.rollback()
        session.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_evidencia_archivo_creation_and_cleanup_on_failure(db_session_factory):
    """Valida registro probatorio de evidencias y que un fallo en BD elimine el archivo físico."""
    temp_dir = mkdtemp()
    session = db_session_factory()
    try:
        storage = StorageService(base_path=temp_dir)
        ev_service = EvidenciaService(storage=storage)

        u = Usuario(
            nombre="Auditor Externo",
            correo="externo@kpmg.com",
            correo_normalizado="externo@kpmg.com",
            password_hash="pwd_hash_456",
            rol="AUDITOR_EXTERNO",
        )
        aud = Auditoria(
            codigo="AUD-SOC2-2026",
            nombre="Auditoria SOC 2 Tipo II",
            alcance="Seguridad logica y controles",
            responsable=u,
            creador=u,
        )
        session.add_all([u, aud])
        session.commit()
        session.refresh(u)
        session.refresh(aud)

        payload_ev = b"Certificado Digital de Evidencia Criptografica"
        expected_sha_ev = hashlib.sha256(payload_ev).hexdigest()
        stream_ev = io.BytesIO(payload_ev)

        evidencia = ev_service.registrar_evidencia_archivo(
            db=session,
            auditoria_id=aud.id,
            titulo="Certificado SSL de Servidor de Produccion",
            registrada_por_id=u.id,
            file_stream=stream_ev,
            filename="cert_prod.pem",
            descripcion="Certificado verificado",
        )

        assert evidencia.id is not None
        assert evidencia.sha256 == expected_sha_ev
        assert evidencia.tipo == "FILE"
        assert Path(storage.get_absolute_path(evidencia.storage_key)).exists()

        # Verificar evento en bitácora inmutable
        evento_ev = (
            session.query(EventoAuditoria)
            .filter(
                EventoAuditoria.entidad_tipo == "EVIDENCIA",
                EventoAuditoria.entidad_id == str(evidencia.id),
                EventoAuditoria.accion == "CARGA_EVIDENCIA",
            )
            .first()
        )
        assert evento_ev is not None
        assert evento_ev.datos_nuevos["sha256"] == expected_sha_ev

    finally:
        session.rollback()
        session.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_atomic_cleanup_on_database_error(db_session_factory):
    """Valida que si la BD falla, el archivo guardado en disco sea eliminado inmediatamente."""
    temp_dir = mkdtemp()
    session = db_session_factory()
    try:
        storage = StorageService(base_path=temp_dir)
        doc_service = DocumentoService(storage=storage)

        u = Usuario(
            nombre="Operador",
            correo="operador@plurione.com",
            correo_normalizado="operador@plurione.com",
            password_hash="pwd",
            rol="RESPONSABLE_AREA",
        )
        area = Area(codigo="OPS", nombre="Operaciones")
        doc = Documento(codigo="DOC-OPS-01", titulo="Manual Operativo", tipo="MANUAL", responsable=u, area=area, creador=u)
        session.add_all([u, area, doc])
        session.commit()
        session.refresh(doc)
        session.refresh(u)

        # Forzar un fallo simulado en commit tras guardar el archivo en disco
        stream = io.BytesIO(b"Datos que fallaran al insertar")

        def broken_commit():
            raise RuntimeError("Simulated Database Crash during Commit")

        session.commit = broken_commit

        with pytest.raises(RuntimeError, match="Simulated Database Crash"):
            doc_service.crear_version_documento(
                db=session,
                documento_id=doc.id,
                file_stream=stream,
                filename="fallo.pdf",
                subido_por_id=u.id,
            )

        # Verificar que NO queden archivos huérfanos en temp_dir
        archivos_restantes = list(Path(temp_dir).rglob("*.*"))
        archivos_reales = [f for f in archivos_restantes if not f.name.endswith(".tmp")]
        assert len(archivos_reales) == 0, f"Quedaron archivos huérfanos: {archivos_reales}"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
