"""SQLAlchemy models for the document traceability domain.

All timestamps are stored as naive UTC values in MySQL DATETIME(6). The
application must convert aware datetimes to UTC before persistence and attach
UTC when reading values returned by MySQL.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    """Return naive UTC for MySQL DATETIME(6), which stores no timezone."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _id_column() -> Any:
    return mysql.BIGINT(unsigned=True)


def _utc_column(*, nullable: bool = False, onupdate: bool = False) -> Any:
    options: dict[str, Any] = {
        "nullable": nullable,
        "default": _utc_now,
    }
    if onupdate:
        options["onupdate"] = _utc_now
        options["server_default"] = text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)")
    else:
        options["server_default"] = func.current_timestamp(6)
    return mapped_column(mysql.DATETIME(fsp=6), **options)


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        UniqueConstraint("correo_normalizado", name="uq_usuarios_correo_normalizado"),
        CheckConstraint(
            "rol IN ('ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO', 'RESPONSABLE_AREA', 'APROBADOR')",
            name="ck_usuarios_rol",
        ),
        Index("ix_usuarios_rol", "rol"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    correo: Mapped[str] = mapped_column(String(320), nullable=False)
    correo_normalizado: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(
        String(30), nullable=False, default="AUDITOR_INTERNO", server_default=text("'AUDITOR_INTERNO'")
    )
    activo: Mapped[bool] = mapped_column(mysql.BOOLEAN(), nullable=False, default=True, server_default=text("1"))
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    auditorias_responsable: Mapped[list[Auditoria]] = relationship(
        back_populates="responsable", foreign_keys="Auditoria.responsable_id"
    )
    auditorias_creadas: Mapped[list[Auditoria]] = relationship(
        back_populates="creador", foreign_keys="Auditoria.created_by_id"
    )
    auditorias_actualizadas: Mapped[list[Auditoria]] = relationship(
        back_populates="editor", foreign_keys="Auditoria.updated_by_id"
    )
    documentos_responsable: Mapped[list[Documento]] = relationship(
        back_populates="responsable", foreign_keys="Documento.responsable_id"
    )
    documentos_creados: Mapped[list[Documento]] = relationship(
        back_populates="creador", foreign_keys="Documento.created_by_id"
    )
    documentos_actualizados: Mapped[list[Documento]] = relationship(
        back_populates="editor", foreign_keys="Documento.updated_by_id"
    )
    versiones_cargadas: Mapped[list[VersionDocumento]] = relationship(back_populates="subido_por")
    evidencias_registradas: Mapped[list[Evidencia]] = relationship(back_populates="registrada_por")
    hallazgos_responsable: Mapped[list[Hallazgo]] = relationship(
        back_populates="responsable", foreign_keys="Hallazgo.responsable_id"
    )
    hallazgos_creados: Mapped[list[Hallazgo]] = relationship(
        back_populates="creador", foreign_keys="Hallazgo.created_by_id"
    )
    hallazgos_cerrados: Mapped[list[Hallazgo]] = relationship(
        back_populates="cerrado_por", foreign_keys="Hallazgo.cerrado_por_id"
    )
    hallazgos_actualizados: Mapped[list[Hallazgo]] = relationship(
        back_populates="editor", foreign_keys="Hallazgo.updated_by_id"
    )
    rondas_solicitadas: Mapped[list[RondaAprobacion]] = relationship(back_populates="solicitada_por")
    decisiones_aprobacion: Mapped[list[DecisionAprobacion]] = relationship(back_populates="aprobador")
    eventos_auditoria: Mapped[list[EventoAuditoria]] = relationship(back_populates="actor")


class Area(Base):
    __tablename__ = "areas"
    __table_args__ = (UniqueConstraint("codigo", name="uq_areas_codigo"),)

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    activa: Mapped[bool] = mapped_column(mysql.BOOLEAN(), nullable=False, default=True, server_default=text("1"))
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    documentos: Mapped[list[Documento]] = relationship(back_populates="area")


class Auditoria(Base):
    __tablename__ = "auditorias"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_auditorias_codigo"),
        CheckConstraint(
            "estado IN ('PLANNED', 'IN_PROGRESS', 'IN_REVIEW', 'COMPLETED', 'CANCELLED')",
            name="ck_auditorias_estado",
        ),
        CheckConstraint(
            "fecha_fin_prevista IS NULL OR fecha_inicio_prevista IS NULL "
            "OR fecha_fin_prevista >= fecha_inicio_prevista",
            name="ck_auditorias_fechas_previstas",
        ),
        CheckConstraint(
            "completada_en IS NULL OR iniciada_en IS NULL OR completada_en >= iniciada_en",
            name="ck_auditorias_fechas_reales",
        ),
        Index("ix_auditorias_estado_inicio", "estado", "fecha_inicio_prevista"),
        Index("ix_auditorias_responsable", "responsable_id"),
        Index("ix_auditorias_created_by", "created_by_id"),
        Index("ix_auditorias_updated_by", "updated_by_id"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    alcance: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(String(24), nullable=False, default="PLANNED", server_default=text("'PLANNED'"))
    fecha_inicio_prevista: Mapped[date | None] = mapped_column(mysql.DATE(), nullable=True)
    fecha_fin_prevista: Mapped[date | None] = mapped_column(mysql.DATE(), nullable=True)
    iniciada_en: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    completada_en: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    responsable_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    created_by_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    responsable: Mapped[Usuario] = relationship(back_populates="auditorias_responsable", foreign_keys=[responsable_id])
    creador: Mapped[Usuario] = relationship(back_populates="auditorias_creadas", foreign_keys=[created_by_id])
    editor: Mapped[Usuario | None] = relationship(back_populates="auditorias_actualizadas", foreign_keys=[updated_by_id])
    documentos_asociados: Mapped[list[DocumentoAuditoria]] = relationship(back_populates="auditoria")
    evidencias: Mapped[list[Evidencia]] = relationship(back_populates="auditoria")
    hallazgos: Mapped[list[Hallazgo]] = relationship(back_populates="auditoria")


class Documento(Base):
    __tablename__ = "documentos"
    __table_args__ = (
        UniqueConstraint("codigo", name="uq_documentos_codigo"),
        CheckConstraint(
            "estado IN ('DRAFT', 'ACTIVE', 'OBSOLETE', 'ARCHIVED')", name="ck_documentos_estado"
        ),
        Index("ix_documentos_estado_area", "estado", "area_id"),
        Index("ix_documentos_area_id", "area_id"),
        Index("ix_documentos_responsable", "responsable_id"),
        Index("ix_documentos_created_by", "created_by_id"),
        Index("ix_documentos_version_vigente", "version_vigente_id"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(80), nullable=False)
    titulo: Mapped[str] = mapped_column(String(240), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    estado: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    responsable_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    area_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("areas.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    created_by_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True
    )
    version_vigente_id: Mapped[int | None] = mapped_column(
        _id_column(),
        ForeignKey(
            "versiones_documento.id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
            name="fk_documentos_version_vigente",
            use_alter=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    responsable: Mapped[Usuario] = relationship(back_populates="documentos_responsable", foreign_keys=[responsable_id])
    area: Mapped[Area] = relationship(back_populates="documentos")
    creador: Mapped[Usuario] = relationship(back_populates="documentos_creados", foreign_keys=[created_by_id])
    editor: Mapped[Usuario | None] = relationship(back_populates="documentos_actualizados", foreign_keys=[updated_by_id])
    version_vigente: Mapped[VersionDocumento | None] = relationship(
        foreign_keys=[version_vigente_id],
        post_update=True,
    )
    versiones: Mapped[list[VersionDocumento]] = relationship(
        back_populates="documento",
        foreign_keys="VersionDocumento.documento_id",
        cascade="all, delete-orphan",
    )
    auditorias_asociadas: Mapped[list[DocumentoAuditoria]] = relationship(
        back_populates="documento",
        foreign_keys="DocumentoAuditoria.documento_id",
    )
    evidencias_relacionadas: Mapped[list[Evidencia]] = relationship(
        back_populates="documento",
        foreign_keys="Evidencia.documento_id",
    )


class VersionDocumento(Base):
    __tablename__ = "versiones_documento"
    __table_args__ = (
        UniqueConstraint("documento_id", "numero_version", name="uq_versiones_documento_numero"),
        UniqueConstraint("storage_key", name="uq_versiones_documento_storage_key"),
        CheckConstraint("numero_version >= 1", name="ck_versiones_documento_numero_positivo"),
        CheckConstraint("tamano_bytes >= 0", name="ck_versiones_documento_tamano_no_negativo"),
        Index("ix_versiones_documento_sha256", "sha256"),
        Index("ix_versiones_documento_subido_por", "subido_por_id"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    documento_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("documentos.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    numero_version: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    nombre_original: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False)
    sha256: Mapped[str] = mapped_column(mysql.CHAR(64), nullable=False)
    comentario_cambio: Mapped[str | None] = mapped_column(Text, nullable=True)
    subido_por_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = _utc_column()

    documento: Mapped[Documento] = relationship(
        back_populates="versiones",
        foreign_keys=[documento_id],
    )
    subido_por: Mapped[Usuario] = relationship(back_populates="versiones_cargadas")
    asociaciones_auditoria: Mapped[list[DocumentoAuditoria]] = relationship(
        back_populates="version_documento",
        foreign_keys="DocumentoAuditoria.version_documento_id",
    )
    evidencias_origen: Mapped[list[Evidencia]] = relationship(
        back_populates="version_documento",
        foreign_keys="Evidencia.version_documento_id",
    )
    rondas_aprobacion: Mapped[list[RondaAprobacion]] = relationship(back_populates="version_documento")


class DocumentoAuditoria(Base):
    __tablename__ = "documentos_auditoria"
    __table_args__ = (
        UniqueConstraint("auditoria_id", "version_documento_id", name="uq_documentos_auditoria_version"),
        CheckConstraint(
            "estado_revision IN ('PENDING', 'REVIEWED', 'ACCEPTED', 'REJECTED')",
            name="ck_documentos_auditoria_estado_revision",
        ),
        Index("ix_documentos_auditoria_estado", "auditoria_id", "estado_revision"),
        Index("ix_documentos_auditoria_documento", "documento_id"),
        Index("ix_documentos_auditoria_version_doc", "version_documento_id"),
        Index("ix_documentos_auditoria_asociado_por", "asociado_por_id"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    auditoria_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("auditorias.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    documento_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("documentos.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    version_documento_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("versiones_documento.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    proposito: Mapped[str] = mapped_column(String(40), nullable=False)
    contexto: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado_revision: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    asociado_por_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    auditoria: Mapped[Auditoria] = relationship(back_populates="documentos_asociados")
    documento: Mapped[Documento] = relationship(back_populates="auditorias_asociadas", foreign_keys=[documento_id])
    version_documento: Mapped[VersionDocumento] = relationship(
        back_populates="asociaciones_auditoria",
        foreign_keys=[version_documento_id],
    )
    asociado_por: Mapped[Usuario] = relationship(foreign_keys=[asociado_por_id])


class Evidencia(Base):
    __tablename__ = "evidencias"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_evidencias_storage_key"),
        CheckConstraint(
            "tipo IN ('FILE', 'REFERENCE', 'NOTE', 'OTHER')", name="ck_evidencias_tipo"
        ),
        CheckConstraint(
            "version_documento_id IS NULL OR documento_id IS NOT NULL",
            name="ck_evidencias_version_requiere_documento",
        ),
        CheckConstraint(
            "tipo <> 'FILE' OR (storage_key IS NOT NULL AND sha256 IS NOT NULL AND tamano_bytes IS NOT NULL)",
            name="ck_evidencias_archivo_campos_completos",
        ),
        CheckConstraint(
            "tipo <> 'REFERENCE' OR referencia_url IS NOT NULL",
            name="ck_evidencias_referencia_url",
        ),
        Index("ix_evidencias_auditoria_tipo", "auditoria_id", "tipo"),
        Index("ix_evidencias_documento", "documento_id"),
        Index("ix_evidencias_version", "version_documento_id"),
        Index("ix_evidencias_sha256", "sha256"),
        Index("ix_evidencias_registrada_por", "registrada_por_id"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    auditoria_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("auditorias.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(24), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    nombre_original: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(127), nullable=True)
    tamano_bytes: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=True), nullable=True)
    sha256: Mapped[str | None] = mapped_column(mysql.CHAR(64), nullable=True)
    referencia_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    documento_id: Mapped[int | None] = mapped_column(
        _id_column(), ForeignKey("documentos.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True
    )
    version_documento_id: Mapped[int | None] = mapped_column(
        _id_column(), ForeignKey("versiones_documento.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True
    )
    registrada_por_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    auditoria: Mapped[Auditoria] = relationship(back_populates="evidencias")
    documento: Mapped[Documento | None] = relationship(
        back_populates="evidencias_relacionadas",
        foreign_keys=[documento_id],
    )
    version_documento: Mapped[VersionDocumento | None] = relationship(
        back_populates="evidencias_origen",
        foreign_keys=[version_documento_id],
    )
    registrada_por: Mapped[Usuario] = relationship(back_populates="evidencias_registradas")
    hallazgo_links: Mapped[list[HallazgoEvidencia]] = relationship(
        back_populates="evidencia",
        foreign_keys="HallazgoEvidencia.evidencia_id",
        cascade="all, delete-orphan",
    )


class Hallazgo(Base):
    __tablename__ = "hallazgos"
    __table_args__ = (
        UniqueConstraint("auditoria_id", "numero", name="uq_hallazgos_auditoria_numero"),
        CheckConstraint("numero >= 1", name="ck_hallazgos_numero_positivo"),
        CheckConstraint(
            "severidad IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="ck_hallazgos_severidad"
        ),
        CheckConstraint(
            "estado IN ('OPEN', 'IN_PROGRESS', 'PENDING_VERIFICATION', 'CLOSED', 'ACCEPTED_RISK')",
            name="ck_hallazgos_estado",
        ),
        CheckConstraint(
            "estado <> 'CLOSED' OR (cerrado_por_id IS NOT NULL AND cerrado_en IS NOT NULL)",
            name="ck_hallazgos_cierre_completo",
        ),
        Index("ix_hallazgos_auditoria_estado", "auditoria_id", "estado"),
        Index("ix_hallazgos_responsable_estado_limite", "responsable_id", "estado", "fecha_limite"),
        Index("ix_hallazgos_detectado_en", "detectado_en"),
        Index("ix_hallazgos_created_by", "created_by_id"),
        Index("ix_hallazgos_cerrado_por", "cerrado_por_id"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    auditoria_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("auditorias.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    numero: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    categoria: Mapped[str] = mapped_column(String(40), nullable=False)
    severidad: Mapped[str] = mapped_column(String(16), nullable=False)
    estado: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN", server_default=text("'OPEN'"))
    responsable_id: Mapped[int | None] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True
    )
    detectado_en: Mapped[datetime] = _utc_column()
    fecha_limite: Mapped[date | None] = mapped_column(mysql.DATE(), nullable=True)
    resolucion: Mapped[str | None] = mapped_column(Text, nullable=True)
    cerrado_por_id: Mapped[int | None] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True
    )
    cerrado_en: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    created_by_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    auditoria: Mapped[Auditoria] = relationship(back_populates="hallazgos")
    responsable: Mapped[Usuario | None] = relationship(
        back_populates="hallazgos_responsable", foreign_keys=[responsable_id]
    )
    cerrado_por: Mapped[Usuario | None] = relationship(
        back_populates="hallazgos_cerrados", foreign_keys=[cerrado_por_id]
    )
    creador: Mapped[Usuario] = relationship(back_populates="hallazgos_creados", foreign_keys=[created_by_id])
    editor: Mapped[Usuario | None] = relationship(back_populates="hallazgos_actualizados", foreign_keys=[updated_by_id])
    evidencia_links: Mapped[list[HallazgoEvidencia]] = relationship(
        back_populates="hallazgo",
        foreign_keys="HallazgoEvidencia.hallazgo_id",
        cascade="all, delete-orphan",
    )


class HallazgoEvidencia(Base):
    __tablename__ = "hallazgos_evidencias"
    __table_args__ = (
        Index("ix_hallazgos_evidencias_evidencia", "evidencia_id", "hallazgo_id"),
        Index("ix_hallazgos_evidencias_vinculada_por", "vinculada_por_id"),
    )

    hallazgo_id: Mapped[int] = mapped_column(
        _id_column(),
        ForeignKey("hallazgos.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        primary_key=True,
    )
    evidencia_id: Mapped[int] = mapped_column(
        _id_column(),
        ForeignKey("evidencias.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        primary_key=True,
    )
    vinculada_por_id: Mapped[int] = mapped_column(
        _id_column(),
        ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    vinculada_en: Mapped[datetime] = _utc_column()
    contexto: Mapped[str | None] = mapped_column(Text, nullable=True)

    hallazgo: Mapped[Hallazgo] = relationship(
        back_populates="evidencia_links",
        foreign_keys=[hallazgo_id],
    )
    evidencia: Mapped[Evidencia] = relationship(
        back_populates="hallazgo_links",
        foreign_keys=[evidencia_id],
    )
    vinculada_por: Mapped[Usuario] = relationship(foreign_keys=[vinculada_por_id])


class RondaAprobacion(Base):
    __tablename__ = "rondas_aprobacion"
    __table_args__ = (
        UniqueConstraint("version_documento_id", "numero_ronda", name="uq_rondas_version_numero"),
        CheckConstraint("numero_ronda >= 1", name="ck_rondas_numero_positivo"),
        CheckConstraint(
            "estado IN ('PENDING', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'CANCELLED')",
            name="ck_rondas_estado",
        ),
        CheckConstraint(
            "estado IN ('PENDING', 'IN_REVIEW') OR resuelta_en IS NOT NULL",
            name="ck_rondas_terminal_resuelta",
        ),
        Index("ix_rondas_version_estado", "version_documento_id", "estado"),
        Index("ix_rondas_solicitada_por", "solicitada_por_id"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    version_documento_id: Mapped[int] = mapped_column(
        _id_column(),
        ForeignKey("versiones_documento.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    numero_ronda: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    estado: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    solicitada_por_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    solicitada_en: Mapped[datetime] = _utc_column()
    resuelta_en: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    version_documento: Mapped[VersionDocumento] = relationship(back_populates="rondas_aprobacion")
    solicitada_por: Mapped[Usuario] = relationship(back_populates="rondas_solicitadas")
    decisiones: Mapped[list[DecisionAprobacion]] = relationship(
        back_populates="ronda",
        cascade="all, delete-orphan",
    )


class DecisionAprobacion(Base):
    __tablename__ = "decisiones_aprobacion"
    __table_args__ = (
        UniqueConstraint("ronda_aprobacion_id", "aprobador_id", name="uq_decisiones_ronda_aprobador"),
        CheckConstraint(
            "estado IN ('PENDING', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED')",
            name="ck_decisiones_estado",
        ),
        CheckConstraint(
            "(estado = 'PENDING' AND decidida_en IS NULL) OR "
            "(estado <> 'PENDING' AND decidida_en IS NOT NULL)",
            name="ck_decisiones_fecha_estado",
        ),
        Index("ix_decisiones_aprobador_estado", "aprobador_id", "estado"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    ronda_aprobacion_id: Mapped[int] = mapped_column(
        _id_column(),
        ForeignKey("rondas_aprobacion.id", ondelete="RESTRICT", onupdate="RESTRICT"),
        nullable=False,
    )
    aprobador_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    estado: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    asignada_en: Mapped[datetime] = _utc_column()
    decidida_en: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
    created_at: Mapped[datetime] = _utc_column()
    updated_at: Mapped[datetime] = _utc_column(onupdate=True)

    ronda: Mapped[RondaAprobacion] = relationship(back_populates="decisiones")
    aprobador: Mapped[Usuario] = relationship(back_populates="decisiones_aprobacion")


class EventoAuditoria(Base):
    __tablename__ = "eventos_auditoria"
    __table_args__ = (
        Index("ix_eventos_entidad_fecha", "entidad_tipo", "entidad_id", "ocurrido_en"),
        Index("ix_eventos_actor_fecha", "actor_id", "ocurrido_en"),
        Index("ix_eventos_correlation_id", "correlation_id"),
        Index("ix_eventos_ocurrido_en", "ocurrido_en"),
    )

    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True
    )
    actor_snapshot: Mapped[str | None] = mapped_column(String(320), nullable=True)
    accion: Mapped[str] = mapped_column(String(60), nullable=False)
    entidad_tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    entidad_id: Mapped[str] = mapped_column(String(80), nullable=False)
    ocurrido_en: Mapped[datetime] = _utc_column()
    correlation_id: Mapped[str | None] = mapped_column(mysql.CHAR(36), nullable=True)
    datos_anteriores: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    datos_nuevos: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    actor: Mapped[Usuario | None] = relationship(back_populates="eventos_auditoria")
