"""separate common and personal learning materials"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_learning_material_scope"
down_revision = "0022_development_task_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "development_learning_materials",
        sa.Column("course_scope", sa.String(length=20), nullable=False, server_default="personal"),
    )


def downgrade() -> None:
    op.drop_column("development_learning_materials", "course_scope")
