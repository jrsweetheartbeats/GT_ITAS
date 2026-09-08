"""bind closed review findings to the resolved workpaper version"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_review_resolution_version"
down_revision = "0018_review_version_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_findings",
        sa.Column("resolved_workpaper_version_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_review_findings_resolved_workpaper_version_id",
        "review_findings",
        "workpaper_versions",
        ["resolved_workpaper_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_review_findings_resolved_workpaper_version_id",
        "review_findings",
        ["resolved_workpaper_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_findings_resolved_workpaper_version_id",
        table_name="review_findings",
    )
    op.drop_constraint(
        "fk_review_findings_resolved_workpaper_version_id",
        "review_findings",
        type_="foreignkey",
    )
    op.drop_column("review_findings", "resolved_workpaper_version_id")
