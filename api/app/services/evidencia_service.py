"""Servicio de dominio para Registro de Evidencias y Trazabilidad Forense."""

from __future__ import annotations

from typing import Any, BinaryIO
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.entities import Auditoria, Documento, EventoAuditoria, Evidencia, Usuario, VersionDocumento
from app.schemas.evidencia import EvidenciaCreate, TipoEvidenciaEnum
from app.services.storage_service import StorageService, storage_service


class EvidenciaService:
    """Gestiona el registro probatorio de evidencias y su trazabilidad inmutable."""

    def __init__(self, storage: StorageService | None = None) -> None:
        self.storage = storage or storage_service

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
    ) -> Evidencia:
        """Registra una evidencia probatoria física (FILE) con hash SHA-256 en streaming.

        Garantiza atómicamente la cadena de custodia: si la BD falla, se elimina el archivo en disco.
        """
        # 1. Validar existencia y estado de la auditoría
        auditoria = db.query(Auditoria).filter(Auditoria.id == auditoria_id).first()
        if not auditoria:
            raise ValueError(f"Auditoría con ID {auditoria_id} no encontrada")
        if auditoria.estado == "CANCELLED":
            raise ValueError("No se pueden asociar evidencias a una auditoría cancelada")

        # 2. Validar que el usuario exista
        actor = db.query(Usuario).filter(Usuario.id == registrada_por_id).first()
        if not actor:
            raise ValueError(f"Usuario con ID {registrada_por_id} no existe")

        # 3. Validar consistencia de documento y versión si fueron provistos
        if version_documento_id is not None:
            ver = db.query(VersionDocumento).filter(VersionDocumento.id == version_documento_id).first()
            if not ver:
                raise ValueError(f"Versión de documento {version_documento_id} no encontrada")
            if documento_id is not None and ver.documento_id != documento_id:
                raise ValueError("La versión indicada no pertenece al documento especificado")
            documento_id = ver.documento_id
        elif documento_id is not None:
            doc = db.query(Documento).filter(Documento.id == documento_id).first()
            if not doc:
                raise ValueError(f"Documento con ID {documento_id} no encontrado")

        # 4. Guardar archivo físico en streaming con cálculo de hash SHA-256
        stored_file = self.storage.save_file(
            file_stream=file_stream,
            filename=filename,
            content_type=content_type,
            category="evidence",
        )

        # 5. Persistencia transaccional
        try:
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

            # Evento inmutable de bitácora
            corr_id = correlation_id or uuid4().hex
            evento = EventoAuditoria(
                actor_id=registrada_por_id,
                actor_snapshot=f"{actor.nombre} <{actor.correo}> ({actor.rol})",
                accion="CARGA_EVIDENCIA",
                entidad_tipo="EVIDENCIA",
                entidad_id=str(evidencia.id),
                correlation_id=corr_id,
                datos_nuevos={
                    "evidencia_id": evidencia.id,
                    "tipo": evidencia.tipo,
                    "titulo": evidencia.titulo,
                    "auditoria_id": evidencia.auditoria_id,
                    "sha256": evidencia.sha256,
                    "storage_key": evidencia.storage_key,
                    "tamano_bytes": evidencia.tamano_bytes,
                    "nombre_original": evidencia.nombre_original,
                    "documento_id": evidencia.documento_id,
                    "version_documento_id": evidencia.version_documento_id,
                    "client_info": client_info or {},
                },
            )
            db.add(evento)
            db.commit()

            db.refresh(evidencia)
            return evidencia

        except Exception:
            db.rollback()
            self.storage.delete_file(stored_file.storage_key)
            raise

    def registrar_evidencia_logica(
        self,
        db: Session,
        evidencia_in: EvidenciaCreate,
        registrada_por_id: int,
        correlation_id: str | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> Evidencia:
        """Registra una evidencia no basada en archivo físico (REFERENCE, NOTE, OTHER)."""
        if evidencia_in.tipo == TipoEvidenciaEnum.FILE:
            raise ValueError("Las evidencias de tipo FILE deben cargarse mediante 'registrar_evidencia_archivo'")

        auditoria = db.query(Auditoria).filter(Auditoria.id == evidencia_in.auditoria_id).first()
        if not auditoria:
            raise ValueError(f"Auditoría {evidencia_in.auditoria_id} no encontrada")

        actor = db.query(Usuario).filter(Usuario.id == registrada_por_id).first()
        if not actor:
            raise ValueError(f"Usuario {registrada_por_id} no existe")

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
            documento_id=evidencia_in.documento_id,
            version_documento_id=evidencia_in.version_documento_id,
            registrada_por_id=registrada_por_id,
        )
        db.add(evidencia)
        db.flush()

        evento = EventoAuditoria(
            actor_id=registrada_por_id,
            actor_snapshot=f"{actor.nombre} <{actor.correo}> ({actor.rol})",
            accion="REGISTRO_EVIDENCIA_LOGICA",
            entidad_tipo="EVIDENCIA",
            entidad_id=str(evidencia.id),
            correlation_id=correlation_id or uuid4().hex,
            datos_nuevos={
                "evidencia_id": evidencia.id,
                "tipo": evidencia.tipo,
                "titulo": evidencia.titulo,
                "auditoria_id": evidencia.auditoria_id,
                "referencia_url": evidencia.referencia_url,
                "client_info": client_info or {},
            },
        )
        db.add(evento)
        db.commit()
        db.refresh(evidencia)
        return evidencia


evidencia_service = EvidenciaService()
