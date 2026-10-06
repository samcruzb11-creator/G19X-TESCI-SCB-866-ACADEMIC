"""Servicio de dominio para Registro de Evidencias y Trazabilidad Forense.

Responsabilidades:
- Recibir un ``UploadFile`` (tipo FILE), guardar el binario con ``StorageService``,
  calcular SHA-256 en streaming y persistir el registro en ``evidencias``.
- Registrar evidencias no físicas (NOTE, REFERENCE, OTHER) con sus FKs validadas.
- Consultar evidencias por ID.
- Garantizar limpieza de archivos físicos ante fallos de BD (cleanup on failure).
- Escribir un ``EventoAuditoria`` inmutable tras cada operación.
"""

from __future__ import annotations

from typing import Any, BinaryIO
from uuid import uuid4
from app.core.config import settings

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Auditoria,
    Documento,
    EventoAuditoria,
    Evidencia,
    Usuario,
    VersionDocumento,
)
from app.services import authorization_service as authz
from app.services import hallazgo_service as findings
from app.schemas.evidencia import EvidenciaCreate, TipoEvidenciaEnum
from app.services.storage_service import StorageService, storage_service
from app.services.file_transaction import commit_stored_file, discard_uncommitted_file, rollback_safely

try:
    from fastapi import UploadFile
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    _HAS_FASTAPI = False
    UploadFile = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers internos (espejo de los de documento_service para mantener autonomía)
# ---------------------------------------------------------------------------

def _require_usuario(db: Session, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise ValueError(f"Usuario con ID {usuario_id} no encontrado")
    return usuario


def _log_evento(
    db: Session,
    *,
    actor: Usuario,
    accion: str,
    entidad_tipo: str,
    entidad_id: int | str,
    correlation_id: str,
    datos_nuevos: dict[str, Any],
    datos_anteriores: dict[str, Any] | None = None,
) -> EventoAuditoria:
    evento = EventoAuditoria(
        actor_id=actor.id,
        actor_snapshot=f"{actor.nombre} <{actor.correo}> ({actor.rol})",
        accion=accion,
        entidad_tipo=entidad_tipo,
        entidad_id=str(entidad_id),
        correlation_id=correlation_id,
        datos_nuevos=datos_nuevos,
        datos_anteriores=datos_anteriores,
    )
    db.add(evento)
    return evento


# ---------------------------------------------------------------------------
# Validaciones de FK de negocio
# ---------------------------------------------------------------------------

def _validar_auditoria(db: Session, auditoria_id: int) -> Auditoria:
    """Verifica que la auditoría exista y no esté cancelada."""
    auditoria = db.get(Auditoria, auditoria_id)
    if not auditoria:
        raise ValueError(f"Auditoría con ID {auditoria_id} no encontrada")
    if auditoria.estado == "CANCELLED":
        raise ValueError("No se pueden asociar evidencias a una auditoría cancelada")
    return auditoria


def _validar_documento_y_version(
    db: Session,
    documento_id: int | None,
    version_documento_id: int | None,
) -> int | None:
    """Valida la consistencia entre documento y versión; retorna el ``documento_id`` resuelto."""
    if version_documento_id is not None:
        version = db.get(VersionDocumento, version_documento_id)
        if not version:
            raise ValueError(f"Versión de documento {version_documento_id} no encontrada")
        if documento_id is not None and version.documento_id != documento_id:
            raise ValueError("La versión indicada no pertenece al documento especificado")
        # Resolvemos el documento_id desde la versión (la FK lo requiere en el modelo)
        return version.documento_id

    if documento_id is not None:
        doc = db.get(Documento, documento_id)
        if not doc:
            raise ValueError(f"Documento con ID {documento_id} no encontrado")

    return documento_id


# ---------------------------------------------------------------------------
# Servicio principal
# ---------------------------------------------------------------------------

class EvidenciaService:
    """Gestiona el registro probatorio de evidencias y su trazabilidad inmutable."""

    def __init__(self, storage: StorageService | None = None) -> None:
        self.storage = storage or storage_service

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def obtener_evidencia(self, db: Session, evidencia_id: int) -> Evidencia | None:
        """Recupera una evidencia por su ID.

        Returns:
            La :class:`Evidencia` o ``None`` si no existe.
        """
        return db.get(Evidencia, evidencia_id)

    def listar_evidencias(
        self, db: Session, limit: int = 50, offset: int = 0,
        auditoria_id: int | None = None,
    ) -> list[Evidencia]:
        """Consulta paginada, con orden estable y filtro opcional por auditoría."""
        query = select(Evidencia)
        if auditoria_id is not None:
            query = query.where(Evidencia.auditoria_id == auditoria_id)
        return list(db.scalars(query.order_by(Evidencia.id).limit(limit).offset(offset)).all())

    # ------------------------------------------------------------------
    # Evidencia tipo FILE — vía BinaryIO (tests / internos)
    # ------------------------------------------------------------------

    def registrar_evidencia_archivo(
        self,
        db: Session,
        auditoria_id: int,
        titulo: str,
        registrada_por_id: int,
        file_stream: BinaryIO,
        filename: str,
        descripcion: str | None = None,
        documento_id: int | None = None,
        version_documento_id: int | None = None,
        content_type: str | None = None,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
        hallazgo_id: int | None = None,
    ) -> Evidencia:
        """Registra una evidencia probatoria física (FILE) con hash SHA-256 en streaming.

        Flujo:
        1. Validar auditoría, usuario, documento/versión.
        2. Guardar binario en disco con SHA-256 en streaming.
        3. Persistir registro ``Evidencia`` en BD.
        4. Escribir ``EventoAuditoria`` inmutable.
        5. Antes del commit se compensa el archivo nuevo; ante commit incierto
           se conserva. Los fallos posteriores al commit nunca lo eliminan.

        Args:
            db:                   Sesión SQLAlchemy activa.
            auditoria_id:         ID de la auditoría destinataria.
            titulo:               Título descriptivo de la evidencia.
            registrada_por_id:    ID del usuario que registra.
            file_stream:          Stream binario abierto (``BinaryIO``).
            filename:             Nombre de archivo original.
            descripcion:          Descripción opcional.
            documento_id:         FK opcional a ``documentos``.
            version_documento_id: FK opcional a ``versiones_documento``.
            content_type:         MIME type declarado por el cliente.
            correlation_id:       UUID para correlacionar con el request HTTP.
            client_info:          Datos opcionales del cliente.

        Returns:
            La :class:`Evidencia` persistida con sus metadatos forenses.
        """
        _validar_auditoria(db, auditoria_id)
        actor = _require_usuario(db, registrada_por_id)
        authz.authorize_evidence_references(db, actor, auditoria_id, documento_id, version_documento_id)
        documento_id = _validar_documento_y_version(db, documento_id, version_documento_id)
        finding = findings.prepare_new_evidence(db, actor, hallazgo_id, auditoria_id)

        # Escritura física + SHA-256 en streaming
        clean_filename = filename.replace('\\', '/').rsplit('/', 1)[-1].strip()
        if not clean_filename or len(clean_filename) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in clean_filename):
            rollback_safely(db)
            raise ValueError('Nombre de archivo invalido')
        if content_type and (len(content_type) > 127 or any(ord(c) < 32 or ord(c) == 127 for c in content_type)):
            rollback_safely(db)
            raise ValueError('Tipo de archivo invalido')
        class LimitedStream:
            total = 0
            def read(self, size=-1):
                chunk = file_stream.read(size)
                self.total += len(chunk)
                if self.total > settings.max_evidence_file_bytes:
                    raise ValueError('El archivo supera el limite de carga')
                return chunk
        try:
            stored_file = self.storage.save_file(
                file_stream=LimitedStream(),
                filename=clean_filename,
                content_type=content_type,
                category="evidence",
            )
        except Exception:
            rollback_safely(db)
            raise

        try:
            if stored_file.tamano_bytes == 0:
                raise ValueError('El archivo esta vacio')
            evidencia = Evidencia(
                auditoria_id=auditoria_id,
                tipo=TipoEvidenciaEnum.FILE.value,
                titulo=titulo,
                descripcion=descripcion,
                storage_key=stored_file.storage_key,
                nombre_original=stored_file.nombre_original,
                mime_type=stored_file.mime_type,
                tamano_bytes=stored_file.tamano_bytes,
                sha256=stored_file.sha256,
                referencia_url=None,
                documento_id=documento_id,
                version_documento_id=version_documento_id,
                registrada_por_id=registrada_por_id,
            )
            db.add(evidencia)
            db.flush()

            corr_id = correlation_id or uuid4().hex
            _log_evento(
                db,
                actor=actor,
                accion="CARGA_EVIDENCIA",
                entidad_tipo="EVIDENCIA",
                entidad_id=evidencia.id,
                correlation_id=corr_id,
                datos_nuevos={
                    "evidencia_id": evidencia.id,
                    "tipo": evidencia.tipo,
                    "titulo": evidencia.titulo,
                    "auditoria_id": evidencia.auditoria_id,
                    "sha256": evidencia.sha256,
                    "tamano_bytes": evidencia.tamano_bytes,
                    "nombre_original": evidencia.nombre_original,
                    "documento_id": evidencia.documento_id,
                    "version_documento_id": evidencia.version_documento_id,
                    "client_info": client_info or {},
                },
            )
            if finding is not None:
                findings.attach_new(db, actor, finding, evidencia)
            db.flush()  # Persist the event before attempting COMMIT.
        except Exception:
            discard_uncommitted_file(db, self.storage, stored_file.storage_key)
            raise

        commit_stored_file(db, self.storage, stored_file.storage_key)
        # Required by the existing expire-on-commit ORM contract; no cleanup here.
        db.refresh(evidencia)
        return evidencia

    # ------------------------------------------------------------------
    # Evidencia tipo FILE — vía UploadFile (routers FastAPI)
    # ------------------------------------------------------------------

    def registrar_evidencia_desde_upload(
        self,
        db: Session,
        auditoria_id: int,
        titulo: str,
        registrada_por_id: int,
        upload_file: "UploadFile",
        descripcion: str | None = None,
        documento_id: int | None = None,
        version_documento_id: int | None = None,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
        hallazgo_id: int | None = None,
    ) -> Evidencia:
        """Adaptador para ``fastapi.UploadFile`` — extrae stream y delega a ``registrar_evidencia_archivo()``.

        Args:
            upload_file: Objeto ``UploadFile`` recibido en el endpoint FastAPI.
            (resto de parámetros: ver ``registrar_evidencia_archivo``).

        Returns:
            La :class:`Evidencia` persistida.
        """
        if not _HAS_FASTAPI:  # pragma: no cover
            raise RuntimeError("FastAPI no está instalado.")

        return self.registrar_evidencia_archivo(
            db=db,
            auditoria_id=auditoria_id,
            titulo=titulo,
            registrada_por_id=registrada_por_id,
            file_stream=upload_file.file,
            filename=upload_file.filename or "archivo_sin_nombre",
            descripcion=descripcion,
            documento_id=documento_id,
            version_documento_id=version_documento_id,
            content_type=upload_file.content_type,
            correlation_id=correlation_id,
            client_info=client_info,
            hallazgo_id=hallazgo_id,
        )

    # ------------------------------------------------------------------
    # Evidencias lógicas (NOTE, REFERENCE, OTHER) — sin archivo físico
    # ------------------------------------------------------------------

    def registrar_evidencia_logica(
        self, db: Session, evidencia_in: EvidenciaCreate, registrada_por_id: int,
        correlation_id: str | None = None, client_info: dict[str, Any] | None = None,
    ) -> Evidencia:
        try:
            return self._registrar_evidencia_logica(db, evidencia_in, registrada_por_id, correlation_id, client_info)
        except Exception:
            rollback_safely(db)
            raise

    def _registrar_evidencia_logica(
        self,
        db: Session,
        evidencia_in: EvidenciaCreate,
        registrada_por_id: int,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> Evidencia:
        """Registra una evidencia no basada en archivo físico (REFERENCE, NOTE, OTHER).

        Args:
            db:                Sesión SQLAlchemy activa.
            evidencia_in:      DTO validado por ``EvidenciaCreate`` (rechaza FILE).
            registrada_por_id: ID del usuario registrador.
            correlation_id:    UUID para correlacionar con el request HTTP.
            client_info:       Datos opcionales del cliente.

        Returns:
            La :class:`Evidencia` persistida.

        Raises:
            ValueError: Si ``evidencia_in.tipo == FILE``, auditoría no existe, o usuario no existe.
        """
        if evidencia_in.tipo == TipoEvidenciaEnum.FILE:
            raise ValueError(
                "Las evidencias de tipo FILE deben cargarse con 'registrar_evidencia_desde_upload'"
            )

        _validar_auditoria(db, evidencia_in.auditoria_id)
        actor = _require_usuario(db, registrada_por_id)
        authz.authorize_evidence_references(db, actor, evidencia_in.auditoria_id, evidencia_in.documento_id, evidencia_in.version_documento_id)
        documento_id = _validar_documento_y_version(
            db, evidencia_in.documento_id, evidencia_in.version_documento_id
        )
        finding = findings.prepare_new_evidence(db, actor, evidencia_in.hallazgo_id, evidencia_in.auditoria_id)

        evidencia = Evidencia(
            auditoria_id=evidencia_in.auditoria_id,
            tipo=evidencia_in.tipo.value,
            titulo=evidencia_in.titulo,
            descripcion=evidencia_in.descripcion,
            storage_key=None,
            nombre_original=None,
            mime_type=None,
            tamano_bytes=None,
            sha256=None,
            referencia_url=evidencia_in.referencia_url,
            documento_id=documento_id,
            version_documento_id=evidencia_in.version_documento_id,
            registrada_por_id=registrada_por_id,
        )
        db.add(evidencia)
        db.flush()

        corr_id = correlation_id or uuid4().hex
        _log_evento(
            db,
            actor=actor,
            accion="REGISTRO_EVIDENCIA_LOGICA",
            entidad_tipo="EVIDENCIA",
            entidad_id=evidencia.id,
            correlation_id=corr_id,
            datos_nuevos={
                "evidencia_id": evidencia.id,
                "tipo": evidencia.tipo,
                "titulo": evidencia.titulo,
                "auditoria_id": evidencia.auditoria_id,
                "referencia_url": evidencia.referencia_url,
                "documento_id": evidencia.documento_id,
                "version_documento_id": evidencia.version_documento_id,
                "client_info": client_info or {},
            },
        )
        if finding is not None:
            findings.attach_new(db, actor, finding, evidencia)
        db.flush()
        db.commit()
        db.refresh(evidencia)
        return evidencia


# ---------------------------------------------------------------------------
# Instancia singleton predeterminada
# ---------------------------------------------------------------------------
evidencia_service = EvidenciaService()
