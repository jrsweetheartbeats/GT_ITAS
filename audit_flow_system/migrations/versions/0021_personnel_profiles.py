"""add reusable personnel contact profiles"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_personnel_profiles"
down_revision = "0020_attachment_uploader"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personnel_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("name", name="uq_personnel_profiles_name"),
    )
    op.create_index("ix_personnel_profiles_user_id", "personnel_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_personnel_profiles_user_id", table_name="personnel_profiles")
    op.drop_table("personnel_profiles")
