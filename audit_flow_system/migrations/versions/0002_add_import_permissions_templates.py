"""add import permissions templates

Revision ID: 0002_design_tables
Revises: 0001_baseline
Create Date: 2026-06-16
"""
from __future__ import annotations

import hashlib
import re

from alembic import op
import sqlalchemy as sa

revision = "0002_design_tables"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def nullable_hash(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalized_text_key(value: str | None) -> str | None:
    normalized = re.sub(r"\s+", "", str(value or "")).lower()
    return normalized or None


def backfill_hashes() -> None:
    conn = op.get_bind()
    for row_id, entity_name in conn.execute(sa.text("SELECT id, entity_name FROM clients")):
        conn.execute(
            sa.text("UPDATE clients SET normalized_entity_name = :value WHERE id = :id"),
            {"id": row_id, "value": normalized_text_key(entity_name)},
        )
    for table_name, source_column, target_column in [
        ("workpapers", "file_path", "file_path_hash"),
        ("attachments", "file_path", "file_path_hash"),
        ("autofill_plan_items", "workbook_path", "workbook_path_hash"),
    ]:
        for row_id, value in conn.execute(sa.text(f"SELECT id, {source_column} FROM {table_name}")):
            conn.execute(
                sa.text(f"UPDATE {table_name} SET {target_column} = :value WHERE id = :id"),
                {"id": row_id, "value": nullable_hash(value)},
            )


def upgrade() -> None:
    op.add_column("clients", sa.Column("normalized_entity_name", sa.String(240), nullable=True))
    op.add_column("workpapers", sa.Column("file_path_hash", sa.String(64), nullable=True))
    op.add_column("attachments", sa.Column("file_path_hash", sa.String(64), nullable=True))
    op.add_column("autofill_plan_items", sa.Column("workbook_path_hash", sa.String(64), nullable=True))
    backfill_hashes()

    op.create_index("ix_clients_normalized_entity_name", "clients", ["normalized_entity_name"])
    op.create_index("uq_clients_normalized_entity_name", "clients", ["normalized_entity_name"], unique=True)
    op.create_index("ix_projects_client_id", "projects", ["client_id"])
    op.create_index("ix_projects_audit_year", "projects", ["audit_year"])
    op.create_index("ix_projects_oa_project_no", "projects", ["oa_project_no"])
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_index("ix_enterprise_contacts_project_id", "enterprise_contacts", ["project_id"])
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    op.create_index(
        "uq_project_members_project_user_module",
        "project_members",
        ["project_id", "user_id", "module"],
        unique=True,
    )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_index("ix_tasks_owner_user_id", "tasks", ["owner_user_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_workpapers_project_id", "workpapers", ["project_id"])
    op.create_index("ix_workpapers_project_code", "workpapers", ["project_id", "code"])
    op.create_index("ix_workpapers_file_path_hash", "workpapers", ["file_path_hash"])
    op.create_index(
        "uq_workpapers_project_file_path_hash",
        "workpapers",
        ["project_id", "file_path_hash"],
        unique=True,
    )
    op.create_index("ix_attachments_project_id", "attachments", ["project_id"])
    op.create_index("ix_attachments_workpaper_id", "attachments", ["workpaper_id"])
    op.create_index("ix_attachments_file_path_hash", "attachments", ["file_path_hash"])
    op.create_index(
        "uq_attachments_project_index_no",
        "attachments",
        ["project_id", "index_no"],
        unique=True,
    )
    op.create_index(
        "uq_attachments_project_file_path_hash",
        "attachments",
        ["project_id", "file_path_hash"],
        unique=True,
    )
    op.create_index("ix_document_requests_project_id", "document_requests", ["project_id"])
    op.create_index("ix_document_requests_uploaded_by_user_id", "document_requests", ["uploaded_by_user_id"])
    op.create_index("ix_document_requests_status", "document_requests", ["status"])
    op.create_index(
        "uq_document_requests_project_code",
        "document_requests",
        ["project_id", "code"],
        unique=True,
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_active", "login_sessions", ["active"])
    op.create_index("ix_autofill_runs_project_id", "autofill_runs", ["project_id"])
    op.create_index("ix_autofill_plan_items_run_id", "autofill_plan_items", ["run_id"])
    op.create_index(
        "ix_autofill_plan_items_workbook_path_hash",
        "autofill_plan_items",
        ["workbook_path_hash"],
    )
    op.create_index("ix_autofill_plan_items_status", "autofill_plan_items", ["status"])
    op.create_index("ix_review_runs_project_id", "review_runs", ["project_id"])
    op.create_index("ix_review_runs_workpaper_id", "review_runs", ["workpaper_id"])
    op.create_index("ix_review_runs_status", "review_runs", ["status"])
    op.create_index("ix_review_findings_run_id", "review_findings", ["run_id"])
    op.create_index("ix_review_findings_status", "review_findings", ["status"])
    op.create_index("ix_review_findings_severity", "review_findings", ["severity"])
    op.create_index("ix_review_steps_workpaper_id", "review_steps", ["workpaper_id"])
    op.create_index("ix_review_steps_reviewer_user_id", "review_steps", ["reviewer_user_id"])
    op.create_index("ix_review_steps_status", "review_steps", ["status"])
    op.create_index(
        "uq_review_steps_workpaper_sequence",
        "review_steps",
        ["workpaper_id", "sequence_no"],
        unique=True,
    )

    op.create_table(
        "feature_modules",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("code", name="uq_feature_modules_code"),
    )
    op.create_table(
        "role_feature_permissions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("feature_module_id", sa.Integer(), sa.ForeignKey("feature_modules.id"), nullable=False),
        sa.Column("can_view", sa.Boolean(), nullable=False),
        sa.Column("can_edit", sa.Boolean(), nullable=False),
        sa.Column("can_manage", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("role_id", "feature_module_id", name="uq_role_feature_permissions_role_module"),
    )
    op.create_index("ix_role_feature_permissions_role_id", "role_feature_permissions", ["role_id"])
    op.create_index(
        "ix_role_feature_permissions_feature_module_id",
        "role_feature_permissions",
        ["feature_module_id"],
    )

    op.create_table(
        "workpaper_templates",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("stage", sa.String(80), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_path_hash", sa.String(64), nullable=True),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("default_enabled", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("code", "version", name="uq_workpaper_templates_code_version"),
    )
    op.create_index("ix_workpaper_templates_code", "workpaper_templates", ["code"])
    op.create_index("ix_workpaper_templates_enabled", "workpaper_templates", ["default_enabled"])
    op.create_index("ix_workpaper_templates_source_path_hash", "workpaper_templates", ["source_path_hash"])

    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_name", sa.String(240), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_path_hash", sa.String(64), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("ix_import_batches_source_type", "import_batches", ["source_type"])
    op.create_index("ix_import_batches_status", "import_batches", ["status"])

    op.create_table(
        "import_records",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("source_key", sa.String(255), nullable=False),
        sa.Column("source_row_no", sa.Integer(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("target_table", sa.String(120), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("batch_id", "source_key", name="uq_import_records_batch_source_key"),
    )
    op.create_index("ix_import_records_batch_id", "import_records", ["batch_id"])
    op.create_index("ix_import_records_source_key", "import_records", ["source_key"])
    op.create_index("ix_import_records_fingerprint", "import_records", ["fingerprint"])
    op.create_index("ix_import_records_target", "import_records", ["target_table", "target_id"])
    op.create_index("ix_import_records_status", "import_records", ["status"])

    op.create_table(
        "import_errors",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("record_id", sa.Integer(), sa.ForeignKey("import_records.id"), nullable=True),
        sa.Column("severity", sa.String(40), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("ix_import_errors_batch_id", "import_errors", ["batch_id"])
    op.create_index("ix_import_errors_record_id", "import_errors", ["record_id"])
    op.create_index("ix_import_errors_severity", "import_errors", ["severity"])


def downgrade() -> None:
    for index_name, table_name in [
        ("ix_import_errors_severity", "import_errors"),
        ("ix_import_errors_record_id", "import_errors"),
        ("ix_import_errors_batch_id", "import_errors"),
    ]:
        op.drop_index(index_name, table_name=table_name)
    op.drop_table("import_errors")
    for index_name in [
        "ix_import_records_status",
        "ix_import_records_target",
        "ix_import_records_fingerprint",
        "ix_import_records_source_key",
        "ix_import_records_batch_id",
    ]:
        op.drop_index(index_name, table_name="import_records")
    op.drop_table("import_records")
    for index_name in ["ix_import_batches_status", "ix_import_batches_source_type"]:
        op.drop_index(index_name, table_name="import_batches")
    op.drop_table("import_batches")
    for index_name in [
        "ix_workpaper_templates_source_path_hash",
        "ix_workpaper_templates_enabled",
        "ix_workpaper_templates_code",
    ]:
        op.drop_index(index_name, table_name="workpaper_templates")
    op.drop_table("workpaper_templates")
    for index_name in [
        "ix_role_feature_permissions_feature_module_id",
        "ix_role_feature_permissions_role_id",
    ]:
        op.drop_index(index_name, table_name="role_feature_permissions")
    op.drop_table("role_feature_permissions")
    op.drop_table("feature_modules")

    for index_name, table_name in [
        ("uq_review_steps_workpaper_sequence", "review_steps"),
        ("ix_review_steps_status", "review_steps"),
        ("ix_review_steps_reviewer_user_id", "review_steps"),
        ("ix_review_steps_workpaper_id", "review_steps"),
        ("ix_review_findings_severity", "review_findings"),
        ("ix_review_findings_status", "review_findings"),
        ("ix_review_findings_run_id", "review_findings"),
        ("ix_review_runs_status", "review_runs"),
        ("ix_review_runs_workpaper_id", "review_runs"),
        ("ix_review_runs_project_id", "review_runs"),
        ("ix_autofill_plan_items_status", "autofill_plan_items"),
        ("ix_autofill_plan_items_workbook_path_hash", "autofill_plan_items"),
        ("ix_autofill_plan_items_run_id", "autofill_plan_items"),
        ("ix_autofill_runs_project_id", "autofill_runs"),
        ("ix_login_sessions_active", "login_sessions"),
        ("ix_login_sessions_user_id", "login_sessions"),
        ("uq_document_requests_project_code", "document_requests"),
        ("ix_document_requests_status", "document_requests"),
        ("ix_document_requests_uploaded_by_user_id", "document_requests"),
        ("ix_document_requests_project_id", "document_requests"),
        ("uq_attachments_project_file_path_hash", "attachments"),
        ("uq_attachments_project_index_no", "attachments"),
        ("ix_attachments_file_path_hash", "attachments"),
        ("ix_attachments_workpaper_id", "attachments"),
        ("ix_attachments_project_id", "attachments"),
        ("uq_workpapers_project_file_path_hash", "workpapers"),
        ("ix_workpapers_file_path_hash", "workpapers"),
        ("ix_workpapers_project_code", "workpapers"),
        ("ix_workpapers_project_id", "workpapers"),
        ("ix_tasks_status", "tasks"),
        ("ix_tasks_owner_user_id", "tasks"),
        ("ix_tasks_project_id", "tasks"),
        ("uq_project_members_project_user_module", "project_members"),
        ("ix_project_members_user_id", "project_members"),
        ("ix_project_members_project_id", "project_members"),
        ("ix_enterprise_contacts_project_id", "enterprise_contacts"),
        ("ix_projects_status", "projects"),
        ("ix_projects_oa_project_no", "projects"),
        ("ix_projects_audit_year", "projects"),
        ("ix_projects_client_id", "projects"),
        ("uq_clients_normalized_entity_name", "clients"),
        ("ix_clients_normalized_entity_name", "clients"),
    ]:
        op.drop_index(index_name, table_name=table_name)

    op.drop_column("autofill_plan_items", "workbook_path_hash")
    op.drop_column("attachments", "file_path_hash")
    op.drop_column("workpapers", "file_path_hash")
    op.drop_column("clients", "normalized_entity_name")
