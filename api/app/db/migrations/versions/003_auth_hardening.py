"""Persistent login budgets and indexed session pruning; no domain data changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_login_limits",
        sa.Column("identifier", sa.String(320, collation="utf8mb4_unicode_ci"), primary_key=True),
        sa.Column("request_window", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("request_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("failure_window", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("failure_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        mysql_engine="InnoDB", mysql_charset="utf8mb4",
    )
    op.create_index("ix_auth_login_limits_expires_at", "auth_login_limits", ["expires_at"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade():
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_login_limits")
