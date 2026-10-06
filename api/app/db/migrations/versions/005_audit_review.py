"""Allow the missing audit review state; preserve all existing rows.

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE auditorias DROP CHECK ck_auditorias_estado, "
               "ADD CONSTRAINT ck_auditorias_estado CHECK "
               "(estado IN ('PLANNED','IN_PROGRESS','IN_REVIEW','COMPLETED','CANCELLED'))")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM auditorias WHERE estado='IN_REVIEW'")):
        raise RuntimeError("Downgrade bloqueado: existen auditorias IN_REVIEW; sin cambios.")
    op.execute("ALTER TABLE auditorias DROP CHECK ck_auditorias_estado, "
               "ADD CONSTRAINT ck_auditorias_estado CHECK "
               "(estado IN ('PLANNED','IN_PROGRESS','COMPLETED','CANCELLED'))")
