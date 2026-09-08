"""retain the validated source payload for training-plan auditability"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_training_source"
down_revision = "0013_training_protocol"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("development_training_plans", sa.Column("schema_version", sa.String(20), nullable=False, server_default="1.0"))
    op.add_column("development_training_plans", sa.Column("source_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("development_training_plans", "source_json")
    op.drop_column("development_training_plans", "schema_version")
