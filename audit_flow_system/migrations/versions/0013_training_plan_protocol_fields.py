"""persist task submission specifications and assessment thresholds"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_training_protocol"
down_revision = "0012_training_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("development_training_tasks", sa.Column("instructions", sa.Text(), nullable=False, server_default=""))
    op.add_column("development_training_tasks", sa.Column("submission_type", sa.String(40), nullable=False, server_default=""))
    op.add_column("development_training_tasks", sa.Column("submission_title", sa.String(240), nullable=False, server_default=""))
    op.add_column("development_training_tasks", sa.Column("submission_requirements", sa.Text(), nullable=False, server_default=""))
    op.add_column("development_monthly_assessments", sa.Column("thresholds_json", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("development_assessment_dimensions", sa.Column("description", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("development_assessment_dimensions", "description")
    op.drop_column("development_monthly_assessments", "thresholds_json")
    op.drop_column("development_training_tasks", "submission_requirements")
    op.drop_column("development_training_tasks", "submission_title")
    op.drop_column("development_training_tasks", "submission_type")
    op.drop_column("development_training_tasks", "instructions")
