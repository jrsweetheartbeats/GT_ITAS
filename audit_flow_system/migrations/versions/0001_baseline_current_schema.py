"""baseline current schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("can_review", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("code", name="uq_automation_rules_code"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=True),
        *timestamp_columns(),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("entity_name", sa.String(240), nullable=False),
        sa.Column("finance_director_name", sa.String(120), nullable=False),
        sa.Column("finance_director_phone", sa.String(80), nullable=False),
        sa.Column("finance_director_email", sa.String(255), nullable=False),
        sa.Column("creator_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("oa_project_no", sa.String(120), nullable=False),
        sa.Column("ims_project_no", sa.String(120), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("entity_name", sa.String(240), nullable=False),
        sa.Column("audit_year", sa.Integer(), nullable=True),
        sa.Column("audit_scope_start", sa.Date(), nullable=True),
        sa.Column("audit_scope_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("creator_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("project_leader_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("manager_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("quality_reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("field_leader_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("first_partner_name", sa.String(120), nullable=False),
        sa.Column("first_partner_email", sa.String(255), nullable=False),
        sa.Column("first_partner_phone", sa.String(80), nullable=False),
        sa.Column("second_partner_name", sa.String(120), nullable=False),
        sa.Column("second_partner_email", sa.String(255), nullable=False),
        sa.Column("second_partner_phone", sa.String(80), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("prior_project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("project_root", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "client_it_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("department", sa.String(160), nullable=False),
        sa.Column("phone", sa.String(80), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("responsibility", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "enterprise_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("department", sa.String(160), nullable=False),
        sa.Column("phone", sa.String(80), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("responsibility", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_on_project", sa.String(120), nullable=False),
        sa.Column("module", sa.String(80), nullable=False),
        sa.Column("workload", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("module", sa.String(80), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "workpapers",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("stage", sa.String(80), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("source_workpaper_id", sa.Integer(), sa.ForeignKey("workpapers.id"), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("preparer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("year_updated", sa.Boolean(), nullable=False),
        sa.Column("extracted_fields_json", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("workpaper_id", sa.Integer(), sa.ForeignKey("workpapers.id"), nullable=True),
        sa.Column("index_no", sa.String(160), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(80), nullable=False),
        sa.Column("referenced_in", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "document_requests",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("control_code", sa.String(80), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *timestamp_columns(),
    )
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("key", name="uq_system_settings_key"),
    )
    op.create_table(
        "login_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("token", sa.String(160), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("token", name="uq_login_sessions_token"),
    )
    op.create_table(
        "autofill_runs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("apply", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("suggestion_count", sa.Integer(), nullable=False),
        sa.Column("workpaper_count", sa.Integer(), nullable=False),
        sa.Column("plan_count", sa.Integer(), nullable=False),
        sa.Column("planned_count", sa.Integer(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "autofill_plan_items",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("autofill_runs.id"), nullable=False),
        sa.Column("rule_id", sa.String(160), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("workbook_path", sa.Text(), nullable=False),
        sa.Column("sheet_name", sa.String(240), nullable=False),
        sa.Column("field", sa.String(240), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("cell", sa.String(120), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "review_runs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("workpaper_id", sa.Integer(), sa.ForeignKey("workpapers.id"), nullable=True),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("report_path", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "review_findings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("review_runs.id"), nullable=False),
        sa.Column("rule_code", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(40), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "review_steps",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("workpaper_id", sa.Integer(), sa.ForeignKey("workpapers.id"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("reviewer_role_code", sa.String(120), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        *timestamp_columns(),
    )


def downgrade() -> None:
    for table_name in [
        "review_steps",
        "review_findings",
        "review_runs",
        "autofill_plan_items",
        "autofill_runs",
        "login_sessions",
        "system_settings",
        "document_requests",
        "attachments",
        "workpapers",
        "tasks",
        "project_members",
        "enterprise_contacts",
        "client_it_contacts",
        "projects",
        "clients",
        "users",
        "automation_rules",
        "roles",
    ]:
        op.drop_table(table_name)
