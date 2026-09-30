"""Revocable authentication sessions; timestamps follow the domain's UTC convention."""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.entities import _id_column


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_usuario", "usuario_id"), {"mysql_engine": "InnoDB"})

    sid: Mapped[str] = mapped_column(String(64, collation="ascii_bin"), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        _id_column(), ForeignKey("usuarios.id", name="fk_auth_sessions_usuario",
                                ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6), nullable=True)
