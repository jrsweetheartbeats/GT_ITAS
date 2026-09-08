"""add alternate quality reviewer configuration

Revision ID: 0025_project_alternate_quality
Revises: 0024_project_type
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0025_project_alternate_quality"
down_revision = "0024_project_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("quality_reviewer_user_ids_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("projects", "quality_reviewer_user_ids_json")
