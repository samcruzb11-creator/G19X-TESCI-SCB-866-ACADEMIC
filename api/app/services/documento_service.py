"""Servicio de dominio para Documentos, Versiones y Trazabilidad Inmutable."""

from __future__ import annotations

from typing import Any, BinaryIO
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.entities import Documento, EventoAuditoria, Usuario, VersionDocumento
from app.schemas.documento import DocumentoCreate
from app.services.storage_service import StorageService, storage_service


class DocumentoService:
    """Gestiona el ciclo de vida documental y la inmutabilidad de sus versiones."""

    def __init__(self, storage: StorageService | None = None) -> None:
        self.storage = storage or storage_service

    def crear_documento(
        self,
        db: Session,
        doc_in: DocumentoCreate,
        creador_id: int,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> Documento:
        """Crea un nuevo documento registrando el evento de auditoría correspondiente."""
        # 1. Validar unicidad del código
        existente = db.query(Documento).filter(Documento.codigo == doc_in.codigo).first()
        if existente:
            raise ValueError(f"Ya existe un documento con el código '{doc_in.codigo}'")

        # 2. Validar que el creador exista
        creador = db.query(Usuario).filter(Usuario.id == creador_id).first()
        if not creador:
            raise ValueError(f"El usuario creador ID {creador_id} no existe")

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
        db.flush()

        # Registro en bitácora inmutable
        evento = EventoAuditoria(
            actor_id=creador_id,
            actor_snapshot=f"{creador.nombre} <{creador.correo}> ({creador.rol})",
            accion="CREACION_DOCUMENTO",
            entidad_tipo="DOCUMENTO",
            entidad_id=str(documento.id),
            correlation_id=correlation_id or uuid4().hex,
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
        db.add(evento)
        db.commit()
        db.refresh(documento)
        return documento

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

        Si la transacción en base de datos falla, se elimina el archivo en disco
        (cleanup on failure) y se revierte la transacción.
        """
        # 1. Bloqueo pesimista sobre el documento para evitar colisión concurrente de versiones
        documento = (
            db.query(Documento)
            .filter(Documento.id == documento_id)
            .with_for_update()
            .first()
        )
        if not documento:
            raise ValueError(f"Documento con ID {documento_id} no encontrado")

        if documento.estado in ("ARCHIVED", "OBSOLETE"):
            raise ValueError(f"No es posible crear versiones para un documento en estado '{documento.estado}'")

        # 2. Validar que el usuario exista
        actor = db.query(Usuario).filter(Usuario.id == subido_por_id).first()
        if not actor:
            raise ValueError(f"El usuario con ID {subido_por_id} no existe")

        # 3. Calcular correlativo de versión
        max_version = (
            db.query(func.max(VersionDocumento.numero_version))
            .filter(VersionDocumento.documento_id == documento_id)
            .scalar()
            or 0
        )
        nuevo_numero_version = max_version + 1

        # 4. Guardar archivo en streaming y calcular hash SHA-256
        stored_file = self.storage.save_file(
            file_stream=file_stream,
            filename=filename,
            content_type=content_type,
            category="documents",
        )

        # 5. Persistencia transaccional con manejo de rollback seguro
        try:
            version = VersionDocumento(
                documento_id=documento_id,
                numero_version=nuevo_numero_version,
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

            # Actualización atómica de la versión vigente
            if actualizar_vigente:
                documento.version_vigente_id = version.id
                documento.updated_by_id = subido_por_id
                if documento.estado == "DRAFT":
                    documento.estado = "ACTIVE"
                db.flush()

            # Registro de auditoría inmutable
            corr_id = correlation_id or uuid4().hex
            evento = EventoAuditoria(
                actor_id=subido_por_id,
                actor_snapshot=f"{actor.nombre} <{actor.correo}> ({actor.rol})",
                accion="CREACION_VERSION",
                entidad_tipo="DOCUMENTO",
                entidad_id=str(documento.id),
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
            db.add(evento)
            db.commit()

            db.refresh(version)
            db.refresh(documento)
            return version

        except Exception:
            db.rollback()
            # Limpieza inmediata del archivo físico si la BD falla
            self.storage.delete_file(stored_file.storage_key)
            raise


documento_service = DocumentoService()
