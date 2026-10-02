"""6C: requests, purpose-bound action tokens, admission and durable mail work."""
from datetime import datetime
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models.entities import _id_column, _utc_column


class AccessRequest(Base):
    __tablename__ = 'access_requests'
    __table_args__ = (
        Index('uq_access_requests_identifier', 'identifier', unique=True),
        Index('ix_access_requests_status_created', 'status', 'created_at'),
        CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','FULFILLED')", name='ck_access_status'),
        CheckConstraint("approved_role IS NULL OR approved_role IN ('ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR')", name='ck_access_role'),
        CheckConstraint("(status='PENDING' AND resolved_by IS NULL AND resolved_at IS NULL AND approved_role IS NULL AND usuario_id IS NULL) OR "
                        "(status='REJECTED' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND approved_role IS NULL AND usuario_id IS NULL) OR "
                        "(status='APPROVED' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND approved_role IS NOT NULL AND usuario_id IS NULL) OR "
                        "(status='FULFILLED' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND approved_role IS NOT NULL AND usuario_id IS NOT NULL)", name='ck_access_resolution'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'},
    )
    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    identifier: Mapped[str] = mapped_column(String(320, collation='utf8mb4_unicode_ci'), nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='PENDING')
    created_at: Mapped[datetime] = _utc_column()
    resolved_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    resolved_by: Mapped[int | None] = mapped_column(_id_column(), ForeignKey('usuarios.id', ondelete='RESTRICT'))
    approved_role: Mapped[str | None] = mapped_column(String(30))
    admin_reason: Mapped[str | None] = mapped_column(String(1000))
    usuario_id: Mapped[int | None] = mapped_column(_id_column(), ForeignKey('usuarios.id', ondelete='RESTRICT'))


class AuthActionLimit(Base):
    __tablename__ = 'auth_action_limits'
    __table_args__ = (Index('ix_auth_action_limits_expires', 'expires_at'), {'mysql_engine': 'InnoDB', 'mysql_charset':'utf8mb4'})
    action: Mapped[str] = mapped_column(String(32), primary_key=True)
    identifier: Mapped[str] = mapped_column(String(320, collation='utf8mb4_unicode_ci'), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    count: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class AuthActionToken(Base):
    __tablename__ = 'auth_action_tokens'
    __table_args__ = (
        CheckConstraint("(purpose='PASSWORD_RESET' AND usuario_id IS NOT NULL AND access_request_id IS NULL) OR "
                        "(purpose='INITIAL_PASSWORD' AND access_request_id IS NOT NULL AND usuario_id IS NULL)", name='ck_action_token_subject'),
        Index('ix_auth_action_tokens_expires', 'expires_at'),
        Index('ix_auth_action_tokens_user', 'usuario_id'),
        Index('ix_auth_action_tokens_request', 'access_request_id'),
        Index('ix_auth_action_tokens_job', 'mail_job_id'),
        {'mysql_engine': 'InnoDB'},
    )
    token_hash: Mapped[bytes] = mapped_column(mysql.BINARY(32), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    mail_job_id: Mapped[int] = mapped_column(_id_column(), ForeignKey('auth_mail_jobs.id', ondelete='RESTRICT'), nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(_id_column(), ForeignKey('usuarios.id', ondelete='RESTRICT'))
    access_request_id: Mapped[int | None] = mapped_column(_id_column(), ForeignKey('access_requests.id', ondelete='RESTRICT'))
    state_fingerprint: Mapped[bytes] = mapped_column(mysql.BINARY(32), nullable=False)
    created_at: Mapped[datetime] = _utc_column()
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))


class AuthMailJob(Base):
    __tablename__ = 'auth_mail_jobs'
    __table_args__ = (
        CheckConstraint("kind IN ('LOOKUP_RESET','PASSWORD_RESET','INITIAL_PASSWORD','PASSWORD_CHANGED')", name='ck_auth_mail_kind'),
        CheckConstraint("kind <> 'LOOKUP_RESET' OR recipient IS NULL", name='ck_lookup_no_recipient'),
        CheckConstraint("(kind='LOOKUP_RESET' AND identifier IS NOT NULL AND usuario_id IS NULL AND access_request_id IS NULL AND state_fingerprint IS NULL AND token_expires_at IS NULL) OR "
                        "(kind IN ('PASSWORD_RESET','PASSWORD_CHANGED') AND identifier IS NULL AND usuario_id IS NOT NULL AND access_request_id IS NULL AND recipient IS NOT NULL AND state_fingerprint IS NOT NULL) OR "
                        "(kind='INITIAL_PASSWORD' AND identifier IS NULL AND usuario_id IS NULL AND access_request_id IS NOT NULL AND recipient IS NOT NULL AND state_fingerprint IS NOT NULL)", name='ck_auth_mail_subject'),
        CheckConstraint("status IN ('PENDING','PROCESSING','DONE','CANCELLED','FAILED')", name='ck_auth_mail_status'),
        Index('ix_auth_mail_jobs_ready', 'status', 'available_at'),
        Index('ix_auth_mail_jobs_lease', 'status', 'locked_until'),
        Index('ix_auth_mail_jobs_created', 'created_at'),
        Index('ix_auth_mail_jobs_lookup', 'kind', 'identifier'),
        {'mysql_engine': 'InnoDB', 'mysql_charset':'utf8mb4'},
    )
    id: Mapped[int] = mapped_column(_id_column(), primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    identifier: Mapped[str | None] = mapped_column(String(320, collation='utf8mb4_unicode_ci'))
    recipient: Mapped[str | None] = mapped_column(String(320))
    state_fingerprint: Mapped[bytes | None] = mapped_column(mysql.BINARY(32))
    token_expires_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    usuario_id: Mapped[int | None] = mapped_column(_id_column(), ForeignKey('usuarios.id', ondelete='RESTRICT'))
    access_request_id: Mapped[int | None] = mapped_column(_id_column(), ForeignKey('access_requests.id', ondelete='RESTRICT'))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='PENDING')
    attempts: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False, default=0)
    lease: Mapped[str | None] = mapped_column(String(32))
    locked_until: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    available_at: Mapped[datetime] = _utc_column()
    created_at: Mapped[datetime] = _utc_column()
