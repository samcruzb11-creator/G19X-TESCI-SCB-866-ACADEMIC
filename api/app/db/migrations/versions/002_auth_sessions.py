"""Add revocable authentication sessions, without modifying existing tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_sessions",
        sa.Column("sid", sa.String(64, collation="ascii_bin"), primary_key=True, nullable=False),
        sa.Column("usuario_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"],
                                name="fk_auth_sessions_usuario", ondelete="RESTRICT", onupdate="RESTRICT"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_auth_sessions_usuario", "auth_sessions", ["usuario_id"])


def downgrade():
    # MySQL cannot drop an index supporting a live FK. Dropping only this table
    # removes its FK/indexes together; existing users/domain tables are untouched.
    # Session records are intentionally lost: outstanding tokens become invalid.
    op.drop_table("auth_sessions")
