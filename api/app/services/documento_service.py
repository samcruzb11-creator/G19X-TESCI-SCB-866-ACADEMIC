"""Servicio de dominio para Documentos, Versiones y Trazabilidad Inmutable.

Responsabilidades:
- Crear cabeceras de documentos y registrar su evento en la bitácora.
- Cargar nuevas versiones con hash SHA-256 y garantizar que ``version_vigente_id``
  apunte siempre a la versión más reciente (opcionalmente).
- Consultar documentos por ID con carga eager de su versión vigente y versiones.
- Actualizar cabecera de un documento (campos de metadatos, no el archivo).
- Registro inmutable de todos los eventos en ``eventos_auditoria``.

Gestión de errores:
- Ante cualquier fallo de BD tras la escritura física, se ejecuta ``delete_file()``
  sobre el archivo recién guardado (cleanup on failure) y se hace ``rollback()``.
"""

from __future__ import annotations

from typing import Any, BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.entities import Documento, EventoAuditoria, Usuario, VersionDocumento
from app.schemas.documento import DocumentoCreate, DocumentoUpdate
from app.services.storage_service import StorageService, storage_service

try:
    from fastapi import UploadFile
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    _HAS_FASTAPI = False
    UploadFile = None  # type: ignore[assignment,misc]

from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _require_usuario(db: Session, usuario_id: int, rol: str | None = None) -> Usuario:
    """Valida que el usuario exista (y opcionalmente que tenga un rol específico)."""
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise ValueError(f"Usuario con ID {usuario_id} no encontrado")
    if rol and usuario.rol != rol:
        raise PermissionError(
            f"El usuario {usuario_id} tiene rol '{usuario.rol}', se requiere '{rol}'"
        )
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
    """Crea y persiste un ``EventoAuditoria`` inmutable en la sesión activa."""
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
# Servicio principal
# ---------------------------------------------------------------------------

class DocumentoService:
    """Gestiona el ciclo de vida documental y la inmutabilidad de sus versiones."""

    def __init__(self, storage: StorageService | None = None) -> None:
        self.storage = storage or storage_service

    # ------------------------------------------------------------------
    # Creación de cabecera
    # ------------------------------------------------------------------

    def crear_documento(
        self,
        db: Session,
        doc_in: DocumentoCreate,
        creador_id: int,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> Documento:
        """Registra la cabecera de un documento nuevo (sin versión aún).

        Args:
            db:             Sesión SQLAlchemy activa.
            doc_in:         DTO validado con los campos del documento.
            creador_id:     ID del usuario que crea el documento.
            correlation_id: UUID externo para correlacionar con el request HTTP.
            client_info:    Datos opcionales del cliente (IP, user-agent, etc.).

        Returns:
            El :class:`Documento` persistido con ``id`` asignado.

        Raises:
            ValueError: Si el código ya existe o el usuario no está registrado.
        """
        # Unicidad del código
        existente = db.scalar(select(Documento).where(Documento.codigo == doc_in.codigo))
        if existente:
            raise ValueError(f"Ya existe un documento con el código '{doc_in.codigo}'")

        creador = _require_usuario(db, creador_id)

        documento = Documento(
            codigo=doc_in.codigo,
            titulo=doc_in.titulo,
            descripcion=doc_in.descripcion,
            tipo=doc_in.tipo,
            estado=doc_in.estado,
            area_id=doc_in.area_id,
            responsable_id=doc_in.responsable_id,
            created_by_id=creador_id,
        )
        db.add(documento)
        db.flush()  # Obtener el ID sin commit aún

        corr_id = correlation_id or uuid4().hex
        _log_evento(
            db,
            actor=creador,
            accion="CREACION_DOCUMENTO",
            entidad_tipo="DOCUMENTO",
            entidad_id=documento.id,
            correlation_id=corr_id,
            datos_nuevos={
                "codigo": documento.codigo,
                "titulo": documento.titulo,
                "tipo": documento.tipo,
                "estado": documento.estado,
                "area_id": documento.area_id,
                "responsable_id": documento.responsable_id,
                "client_info": client_info or {},
            },
        )
        db.commit()
        db.refresh(documento)
        return documento

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def obtener_documento(
        self,
        db: Session,
        documento_id: int,
        cargar_versiones: bool = False,
    ) -> Documento | None:
        """Recupera un documento por su ID con carga eager opcional de versiones.

        Args:
            db:               Sesión SQLAlchemy activa.
            documento_id:     PK del documento.
            cargar_versiones: Si ``True``, carga también ``documento.versiones``.

        Returns:
            El :class:`Documento` o ``None`` si no existe.
        """
        stmt = (
            select(Documento)
            .where(Documento.id == documento_id)
            .options(joinedload(Documento.version_vigente))
        )
        if cargar_versiones:
            stmt = stmt.options(joinedload(Documento.versiones))

        return db.scalar(stmt)

    def listar_versiones(self, db: Session, documento_id: int) -> list[VersionDocumento]:
        """Retorna todas las versiones de un documento ordenadas por número de versión."""
        stmt = (
            select(VersionDocumento)
            .where(VersionDocumento.documento_id == documento_id)
            .order_by(VersionDocumento.numero_version)
        )
        return list(db.scalars(stmt).all())

    # ------------------------------------------------------------------
    # Actualización de cabecera
    # ------------------------------------------------------------------

    def actualizar_cabecera(
        self,
        db: Session,
        documento_id: int,
        doc_update: DocumentoUpdate,
        editor_id: int,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> Documento:
        """Actualiza los campos de metadatos de un documento (PATCH semántico).

        Solo modifica los campos que vienen con valor distinto de ``None``.

        Raises:
            ValueError: Si el documento no existe o el usuario no existe.
            PermissionError: Si el estado destino no es válido.
        """
        documento = db.get(Documento, documento_id)
        if not documento:
            raise ValueError(f"Documento con ID {documento_id} no encontrado")

        editor = _require_usuario(db, editor_id)

        # Snapshot previo para la bitácora
        datos_anteriores = {
            "titulo": documento.titulo,
            "descripcion": documento.descripcion,
            "tipo": documento.tipo,
            "estado": documento.estado,
            "area_id": documento.area_id,
            "responsable_id": documento.responsable_id,
        }

        # Aplicar únicamente los campos provistos
        update_data = doc_update.model_dump(exclude_unset=True)
        for campo, valor in update_data.items():
            setattr(documento, campo, valor)

        documento.updated_by_id = editor_id
        db.flush()

        corr_id = correlation_id or uuid4().hex
        _log_evento(
            db,
            actor=editor,
            accion="ACTUALIZACION_DOCUMENTO",
            entidad_tipo="DOCUMENTO",
            entidad_id=documento.id,
            correlation_id=corr_id,
            datos_anteriores=datos_anteriores,
            datos_nuevos={**update_data, "client_info": client_info or {}},
        )
        db.commit()
        db.refresh(documento)
        return documento

    # ------------------------------------------------------------------
    # Nueva versión (BinaryIO — para uso interno / tests)
    # ------------------------------------------------------------------

    def crear_version_documento(
        self,
        db: Session,
        documento_id: int,
        file_stream: BinaryIO,
        filename: str,
        subido_por_id: int,
        comentario_cambio: str | None = None,
        content_type: str | None = None,
        actualizar_vigente: bool = True,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> VersionDocumento:
        """Carga una nueva versión física con hash SHA-256 en streaming de forma atómica.

        Flujo:
        1. Bloqueo pesimista (``SELECT ... FOR UPDATE``) sobre el documento.
        2. Cálculo del número de versión siguiente.
        3. Escritura del archivo con hash SHA-256 en streaming.
        4. Persistencia en BD + actualización de ``version_vigente_id``.
        5. Registro inmutable en ``eventos_auditoria``.

        Si paso 4 o 5 falla → ``rollback()`` + ``delete_file()`` (cleanup on failure).

        Args:
            db:               Sesión SQLAlchemy activa.
            documento_id:     ID del documento padre.
            file_stream:      Stream binario ya abierto (``BinaryIO``).
            filename:         Nombre de archivo original.
            subido_por_id:    ID del usuario que sube la versión.
            comentario_cambio: Descripción opcional del cambio.
            content_type:     MIME type declarado por el cliente.
            actualizar_vigente: Si ``True``, actualiza ``version_vigente_id`` y pasa a ACTIVE.
            correlation_id:   UUID para correlacionar con el request HTTP.
            client_info:      Datos opcionales del cliente.

        Returns:
            La :class:`VersionDocumento` persistida.

        Raises:
            ValueError: Si el documento no existe, está archivado, o el usuario no existe.
        """
        # Bloqueo pesimista para serializar versiones concurrentes
        documento = db.scalar(
            select(Documento)
            .where(Documento.id == documento_id)
            .with_for_update()
        )
        if not documento:
            raise ValueError(f"Documento con ID {documento_id} no encontrado")
        if documento.estado in ("ARCHIVED", "OBSOLETE"):
            raise ValueError(
                f"No se pueden agregar versiones a un documento en estado '{documento.estado}'"
            )

        actor = _require_usuario(db, subido_por_id)

        # Número de versión secuencial
        max_version = db.scalar(
            select(func.max(VersionDocumento.numero_version)).where(
                VersionDocumento.documento_id == documento_id
            )
        ) or 0
        nuevo_numero = max_version + 1

        # Escritura física en streaming + SHA-256
        stored_file = self.storage.save_file(
            file_stream=file_stream,
            filename=filename,
            content_type=content_type,
            category="documents",
        )

        # Persistencia atómica — si falla, limpiamos el archivo
        try:
            version = VersionDocumento(
                documento_id=documento_id,
                numero_version=nuevo_numero,
                storage_key=stored_file.storage_key,
                nombre_original=stored_file.nombre_original,
                mime_type=stored_file.mime_type,
                tamano_bytes=stored_file.tamano_bytes,
                sha256=stored_file.sha256,
                comentario_cambio=comentario_cambio,
                subido_por_id=subido_por_id,
            )
            db.add(version)
            db.flush()

            if actualizar_vigente:
                documento.version_vigente_id = version.id
                documento.updated_by_id = subido_por_id
                if documento.estado == "DRAFT":
                    documento.estado = "ACTIVE"
                db.flush()

            corr_id = correlation_id or uuid4().hex
            _log_evento(
                db,
                actor=actor,
                accion="CREACION_VERSION",
                entidad_tipo="DOCUMENTO",
                entidad_id=documento.id,
                correlation_id=corr_id,
                datos_nuevos={
                    "version_id": version.id,
                    "numero_version": version.numero_version,
                    "storage_key": version.storage_key,
                    "nombre_original": version.nombre_original,
                    "mime_type": version.mime_type,
                    "tamano_bytes": version.tamano_bytes,
                    "sha256": version.sha256,
                    "comentario_cambio": version.comentario_cambio,
                    "version_vigente_actualizada": actualizar_vigente,
                    "client_info": client_info or {},
                },
            )
            db.commit()
            db.refresh(version)
            db.refresh(documento)
            return version

        except Exception:
            db.rollback()
            self.storage.delete_file(stored_file.storage_key)  # cleanup on failure
            raise

    # ------------------------------------------------------------------
    # Nueva versión (UploadFile — para routers FastAPI)
    # ------------------------------------------------------------------

    def crear_version_desde_upload(
        self,
        db: Session,
        documento_id: int,
        upload_file: "UploadFile",
        subido_por_id: int,
        comentario_cambio: str | None = None,
        actualizar_vigente: bool = True,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> VersionDocumento:
        """Adaptador de ``crear_version_documento()`` para ``fastapi.UploadFile``.

        Extrae el stream y el nombre del ``UploadFile`` y delega la lógica completa.
        """
        if not _HAS_FASTAPI:  # pragma: no cover
            raise RuntimeError("FastAPI no está instalado.")

        return self.crear_version_documento(
            db=db,
            documento_id=documento_id,
            file_stream=upload_file.file,
            filename=upload_file.filename or "archivo_sin_nombre",
            subido_por_id=subido_por_id,
            comentario_cambio=comentario_cambio,
            content_type=upload_file.content_type,
            actualizar_vigente=actualizar_vigente,
            correlation_id=correlation_id,
            client_info=client_info,
        )


# ---------------------------------------------------------------------------
# Instancia singleton predeterminada
# ---------------------------------------------------------------------------
documento_service = DocumentoService()
