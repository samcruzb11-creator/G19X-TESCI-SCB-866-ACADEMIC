"""Revocable authentication sessions; timestamps follow the domain's UTC convention."""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.entities import _id_column


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_usuario", "usuario_id"),
                      Index("ix_auth_sessions_expires_at", "expires_at"), {"mysql_engine": "InnoDB"})

    sid: Mapped[str] = mapped_column(String(64, collation="ascii_bin"), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", name="fk_auth_sessions_usuario",
                                ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)


class AuthLoginLimit(Base):
    __tablename__ = "auth_login_limits"
    __table_args__ = (Index("ix_auth_login_limits_expires_at", "expires_at"),
                     {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"})

    identifier: Mapped[str] = mapped_column(String(320, collation="utf8mb4_unicode_ci"), primary_key=True)
    request_window: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    request_count: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    failure_window: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    failure_count: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
