"""record attachment uploader for project-member bulk imports"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_attachment_uploader"
down_revision = "0019_review_resolution_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_attachments_uploaded_by_user_id",
        "attachments",
        "users",
        ["uploaded_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_attachments_uploaded_by_user_id", "attachments", ["uploaded_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_attachments_uploaded_by_user_id", table_name="attachments")
    op.drop_constraint("fk_attachments_uploaded_by_user_id", "attachments", type_="foreignkey")
    op.drop_column("attachments", "uploaded_by_user_id")
