"""add project reviewer assignments and immutable review histories"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_project_review_closure"
down_revision = "0016_blocker_escalation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("director_user_id", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("partner_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_projects_director_user_id", "projects", "users", ["director_user_id"], ["id"])
    op.create_foreign_key("fk_projects_partner_user_id", "projects", "users", ["partner_user_id"], ["id"])
    op.execute(sa.text("""
        UPDATE projects p
        SET p.project_leader_user_id = (
            SELECT pm.user_id FROM project_members pm
            JOIN users u ON u.id = pm.user_id JOIN roles r ON r.id = u.role_id
            WHERE pm.project_id = p.id AND r.code = 'manager' ORDER BY pm.id LIMIT 1
        )
        WHERE p.project_leader_user_id IS NULL
    """))
    op.execute(sa.text("""
        UPDATE projects p
        SET p.manager_user_id = COALESCE(
            (SELECT pm.user_id FROM project_members pm JOIN users u ON u.id = pm.user_id JOIN roles r ON r.id = u.role_id WHERE pm.project_id = p.id AND r.code = 'senior_manager' ORDER BY pm.id LIMIT 1),
            p.project_leader_user_id
        )
        WHERE p.manager_user_id IS NULL
    """))
    for column_name, role_code in (
        ("quality_reviewer_user_id", "quality"),
        ("director_user_id", "director"),
        ("partner_user_id", "partner"),
    ):
        op.execute(sa.text(f"""
            UPDATE projects p
            SET p.{column_name} = (
                SELECT pm.user_id FROM project_members pm
                JOIN users u ON u.id = pm.user_id JOIN roles r ON r.id = u.role_id
                WHERE pm.project_id = p.id AND r.code = '{role_code}' ORDER BY pm.id LIMIT 1
            )
            WHERE p.{column_name} IS NULL
        """))

    op.create_table(
        "workpaper_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workpaper_id", sa.Integer(), sa.ForeignKey("workpapers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False, server_default=""),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workpaper_id", "version_no", name="uq_workpaper_versions_workpaper_version"),
    )
    op.create_index("ix_workpaper_versions_workpaper_id", "workpaper_versions", ["workpaper_id"])
    op.create_index("ix_workpaper_versions_uploaded_by_user_id", "workpaper_versions", ["uploaded_by_user_id"])

    op.create_table(
        "review_finding_responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("review_findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("responder_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("attachment", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("finding_id", "round_no", name="uq_review_finding_responses_finding_round"),
    )
    op.create_index("ix_review_finding_responses_finding_id", "review_finding_responses", ["finding_id"])
    op.create_index("ix_review_finding_responses_responder_user_id", "review_finding_responses", ["responder_user_id"])

    op.add_column("review_steps", sa.Column("round_no", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "review_step_histories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("review_steps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operator_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("round_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("old_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("new_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_review_step_histories_step_id", "review_step_histories", ["step_id"])
    op.create_index("ix_review_step_histories_operator_user_id", "review_step_histories", ["operator_user_id"])


def downgrade() -> None:
    op.drop_index("ix_review_step_histories_operator_user_id", table_name="review_step_histories")
    op.drop_index("ix_review_step_histories_step_id", table_name="review_step_histories")
    op.drop_table("review_step_histories")
    op.drop_column("review_steps", "round_no")

    op.drop_index("ix_review_finding_responses_responder_user_id", table_name="review_finding_responses")
    op.drop_index("ix_review_finding_responses_finding_id", table_name="review_finding_responses")
    op.drop_table("review_finding_responses")

    op.drop_index("ix_workpaper_versions_uploaded_by_user_id", table_name="workpaper_versions")
    op.drop_index("ix_workpaper_versions_workpaper_id", table_name="workpaper_versions")
    op.drop_table("workpaper_versions")

    op.drop_constraint("fk_projects_partner_user_id", "projects", type_="foreignkey")
    op.drop_constraint("fk_projects_director_user_id", "projects", type_="foreignkey")
    op.drop_column("projects", "partner_user_id")
    op.drop_column("projects", "director_user_id")
