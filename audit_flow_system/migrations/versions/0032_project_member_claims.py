"""add project member claim workflow"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0032_project_member_claims"
down_revision = "0031_ims_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_member_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member_claims_project_user"),
    )
    op.create_index("ix_project_member_claims_project_status", "project_member_claims", ["project_id", "status"])
    op.create_index("ix_project_member_claims_user_status", "project_member_claims", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_project_member_claims_user_status", table_name="project_member_claims")
    op.drop_index("ix_project_member_claims_project_status", table_name="project_member_claims")
    op.drop_table("project_member_claims")
