"""bind review records to workpaper versions and enforce unique codes"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_review_version_scope"
down_revision = "0017_project_review_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_workpapers_project_code", "workpapers", ["project_id", "code"])

    op.add_column("review_findings", sa.Column("workpaper_id", sa.Integer(), nullable=True))
    op.add_column("review_findings", sa.Column("workpaper_version_id", sa.Integer(), nullable=True))
    op.add_column("review_findings", sa.Column("review_step_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_review_findings_workpaper_id", "review_findings", "workpapers", ["workpaper_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_review_findings_workpaper_version_id", "review_findings", "workpaper_versions", ["workpaper_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_review_findings_review_step_id", "review_findings", "review_steps", ["review_step_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_review_findings_workpaper_id", "review_findings", ["workpaper_id"])
    op.create_index("ix_review_findings_workpaper_version_id", "review_findings", ["workpaper_version_id"])
    op.create_index("ix_review_findings_review_step_id", "review_findings", ["review_step_id"])

    op.add_column("review_steps", sa.Column("workpaper_version_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_review_steps_workpaper_version_id", "review_steps", "workpaper_versions", ["workpaper_version_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_review_steps_workpaper_version_id", "review_steps", ["workpaper_version_id"])

    op.add_column("review_step_histories", sa.Column("workpaper_version_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_review_step_histories_workpaper_version_id", "review_step_histories", "workpaper_versions", ["workpaper_version_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_review_step_histories_workpaper_version_id", "review_step_histories", ["workpaper_version_id"])


def downgrade() -> None:
    op.drop_index("ix_review_step_histories_workpaper_version_id", table_name="review_step_histories")
    op.drop_constraint("fk_review_step_histories_workpaper_version_id", "review_step_histories", type_="foreignkey")
    op.drop_column("review_step_histories", "workpaper_version_id")

    op.drop_index("ix_review_steps_workpaper_version_id", table_name="review_steps")
    op.drop_constraint("fk_review_steps_workpaper_version_id", "review_steps", type_="foreignkey")
    op.drop_column("review_steps", "workpaper_version_id")

    op.drop_index("ix_review_findings_review_step_id", table_name="review_findings")
    op.drop_index("ix_review_findings_workpaper_version_id", table_name="review_findings")
    op.drop_index("ix_review_findings_workpaper_id", table_name="review_findings")
    op.drop_constraint("fk_review_findings_review_step_id", "review_findings", type_="foreignkey")
    op.drop_constraint("fk_review_findings_workpaper_version_id", "review_findings", type_="foreignkey")
    op.drop_constraint("fk_review_findings_workpaper_id", "review_findings", type_="foreignkey")
    op.drop_column("review_findings", "review_step_id")
    op.drop_column("review_findings", "workpaper_version_id")
    op.drop_column("review_findings", "workpaper_id")

    op.drop_constraint("uq_workpapers_project_code", "workpapers", type_="unique")
