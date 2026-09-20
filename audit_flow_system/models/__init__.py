from __future__ import annotations

from datetime import date, datetime
import hashlib
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base


def normalized_text_key(value: str) -> str:
    return "".join(str(value or "").split()).lower()


def nullable_hash(value: str) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    can_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    role_id: Mapped[Optional[int]] = mapped_column(ForeignKey("roles.id"), nullable=True)

    role: Mapped[Optional[Role]] = relationship(back_populates="users")


class PersonnelProfile(TimestampMixin, Base):
    """Reusable staff contact data, kept separately from login credentials."""
    __tablename__ = "personnel_profiles"
    __table_args__ = (
        UniqueConstraint("name", name="uq_personnel_profiles_name"),
        Index("ix_personnel_profiles_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)

    user: Mapped[Optional[User]] = relationship(foreign_keys=[user_id])


class ImsContact(TimestampMixin, Base):
    """Firm-wide IMS address book, synced from the production directory."""
    __tablename__ = "ims_contacts"
    __table_args__ = (
        Index("ix_ims_contacts_workcode", "workcode"),
        Index("ix_ims_contacts_lastname", "lastname"),
        Index("ix_ims_contacts_email", "email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    lastname: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    workcode: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    sex: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    department: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    department_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    subcompany: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    subcompany_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    job_title: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    job_activity: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    job_group: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    rank_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    mobile: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    telephone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    fax: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    extension: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    manager: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    manager_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    dsporder: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_time", "user_id", "occurred_at"),
        Index("ix_audit_logs_action_time", "action", "occurred_at"),
        Index("ix_audit_logs_project_time", "project_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    success: Mapped[bool] = mapped_column(default=True, nullable=False)
    ip_address: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[Optional[User]] = relationship(foreign_keys=[user_id])


class Client(TimestampMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (
        Index("ix_clients_normalized_entity_name", "normalized_entity_name"),
        UniqueConstraint("normalized_entity_name", name="uq_clients_normalized_entity_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_entity_name: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    finance_director_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    finance_director_phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    finance_director_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    creator_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    creator: Mapped[Optional[User]] = relationship()
    it_contacts: Mapped[list["ClientITContact"]] = relationship(cascade="all, delete-orphan")


class ClientITContact(TimestampMixin, Base):
    __tablename__ = "client_it_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    department: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    responsibility: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_client_id", "client_id"),
        Index("ix_projects_audit_year", "audit_year"),
        Index("ix_projects_oa_project_no", "oa_project_no"),
        Index("ix_projects_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    project_type: Mapped[str] = mapped_column(String(40), default="it_audit", nullable=False)
    code: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    oa_project_no: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    ims_project_no: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)
    entity_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    audit_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    audit_scope_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    audit_scope_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="planning", nullable=False)
    creator_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    project_leader_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    manager_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    quality_reviewer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    quality_reviewer_user_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    field_leader_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    director_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    partner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    first_partner_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    first_partner_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    first_partner_phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    second_partner_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    second_partner_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    second_partner_phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    prior_project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True)
    project_root: Mapped[str] = mapped_column(Text, default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    department: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    scope_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    business_revenue: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    charge_with_tax: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    charge_without_tax: Mapped[str] = mapped_column(String(80), default="", nullable=False)

    client: Mapped[Optional[Client]] = relationship(foreign_keys=[client_id])
    creator: Mapped[Optional[User]] = relationship(foreign_keys=[creator_user_id])
    project_leader: Mapped[Optional[User]] = relationship(foreign_keys=[project_leader_user_id])
    manager: Mapped[Optional[User]] = relationship(foreign_keys=[manager_user_id])
    quality_reviewer: Mapped[Optional[User]] = relationship(foreign_keys=[quality_reviewer_user_id])
    field_leader: Mapped[Optional[User]] = relationship(foreign_keys=[field_leader_user_id])
    director: Mapped[Optional[User]] = relationship(foreign_keys=[director_user_id])
    partner: Mapped[Optional[User]] = relationship(foreign_keys=[partner_user_id])
    prior_project: Mapped[Optional["Project"]] = relationship(remote_side=[id])
    contacts: Mapped[list["EnterpriseContact"]] = relationship(cascade="all, delete-orphan")
    members: Mapped[list["ProjectMember"]] = relationship(cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(cascade="all, delete-orphan")
    workpapers: Mapped[list["Workpaper"]] = relationship(cascade="all, delete-orphan")
    attachments: Mapped[list["Attachment"]] = relationship(cascade="all, delete-orphan")
    document_requests: Mapped[list["DocumentRequest"]] = relationship(cascade="all, delete-orphan")
    review_runs: Mapped[list["ReviewRun"]] = relationship(cascade="all, delete-orphan")
    autofill_runs: Mapped[list["AutofillRun"]] = relationship(cascade="all, delete-orphan")
    rule_manual_corrections: Mapped[list["RuleManualCorrection"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    rule_manual_correction_imports: Mapped[list["RuleManualCorrectionImport"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    autofill_rule_actions: Mapped[list["AutofillRuleAction"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class EnterpriseContact(TimestampMixin, Base):
    __tablename__ = "enterprise_contacts"
    __table_args__ = (Index("ix_enterprise_contacts_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    department: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    responsibility: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ProjectMember(TimestampMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", "module", name="uq_project_members_project_user_module"),
        Index("ix_project_members_project_id", "project_id"),
        Index("ix_project_members_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role_on_project: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    module: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    workload: Mapped[str] = mapped_column(Text, default="", nullable=False)

    user: Mapped[User] = relationship()


class ProjectMemberClaim(TimestampMixin, Base):
    """A staff member's request to join a project, pending project approval."""
    __tablename__ = "project_member_claims"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_claims_project_user"),
        Index("ix_project_member_claims_project_status", "project_id", "status"),
        Index("ix_project_member_claims_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    reviewer: Mapped[Optional[User]] = relationship(foreign_keys=[reviewer_user_id])


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_id", "project_id"),
        Index("ix_tasks_owner_user_id", "owner_user_id"),
        Index("ix_tasks_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    module: Mapped[str] = mapped_column(String(80), default="ITGC", nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)

    owner: Mapped[Optional[User]] = relationship()


class Workpaper(TimestampMixin, Base):
    __tablename__ = "workpapers"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_workpapers_project_code"),
        UniqueConstraint("project_id", "file_path_hash", name="uq_workpapers_project_file_path_hash"),
        Index("ix_workpapers_project_id", "project_id"),
        Index("ix_workpapers_project_code", "project_id", "code"),
        Index("ix_workpapers_file_path_hash", "file_path_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    stage: Mapped[str] = mapped_column(String(80), default="execution", nullable=False)
    file_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    file_path_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_workpaper_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workpapers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    preparer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    year_updated: Mapped[bool] = mapped_column(default=False, nullable=False)
    extracted_fields_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    preparer: Mapped[Optional[User]] = relationship(foreign_keys=[preparer_user_id])
    versions: Mapped[list["WorkpaperVersion"]] = relationship(cascade="all, delete-orphan")


class WorkpaperVersion(TimestampMixin, Base):
    __tablename__ = "workpaper_versions"
    __table_args__ = (
        UniqueConstraint("workpaper_id", "version_no", name="uq_workpaper_versions_workpaper_version"),
        Index("ix_workpaper_versions_workpaper_id", "workpaper_id"),
        Index("ix_workpaper_versions_uploaded_by_user_id", "uploaded_by_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("workpapers.id", ondelete="CASCADE"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    uploaded_by: Mapped[Optional[User]] = relationship(foreign_keys=[uploaded_by_user_id])


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint("project_id", "index_no", name="uq_attachments_project_index_no"),
        UniqueConstraint("project_id", "file_path_hash", name="uq_attachments_project_file_path_hash"),
        Index("ix_attachments_project_id", "project_id"),
        Index("ix_attachments_workpaper_id", "workpaper_id"),
        Index("ix_attachments_uploaded_by_user_id", "uploaded_by_user_id"),
        Index("ix_attachments_file_path_hash", "file_path_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    workpaper_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workpapers.id"), nullable=True)
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    index_no: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    file_path_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    referenced_in: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)

    uploaded_by: Mapped[Optional[User]] = relationship(foreign_keys=[uploaded_by_user_id])


class DocumentRequest(TimestampMixin, Base):
    __tablename__ = "document_requests"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_document_requests_project_code"),
        Index("ix_document_requests_project_id", "project_id"),
        Index("ix_document_requests_uploaded_by_user_id", "uploaded_by_user_id"),
        Index("ix_document_requests_status", "status"),
        Index("ix_document_requests_due_date", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    control_code: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    direction: Mapped[str] = mapped_column(Text, default="", nullable=False)
    required: Mapped[bool] = mapped_column(default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    file_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AutomationRule(TimestampMixin, Base):
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(40), default="medium", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SystemSetting(TimestampMixin, Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)


class LoginSession(TimestampMixin, Base):
    __tablename__ = "login_sessions"
    __table_args__ = (
        Index("ix_login_sessions_user_id", "user_id"),
        Index("ix_login_sessions_active", "active"),
        Index("ix_login_sessions_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped[User] = relationship()


class AutofillRun(TimestampMixin, Base):
    __tablename__ = "autofill_runs"
    __table_args__ = (Index("ix_autofill_runs_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    apply: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="completed", nullable=False)
    suggestion_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    workpaper_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    plan_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    planned_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    items: Mapped[list["AutofillPlanItem"]] = relationship(cascade="all, delete-orphan")


class AutofillPlanItem(TimestampMixin, Base):
    __tablename__ = "autofill_plan_items"
    __table_args__ = (
        Index("ix_autofill_plan_items_run_id", "run_id"),
        Index("ix_autofill_plan_items_workbook_path_hash", "workbook_path_hash"),
        Index("ix_autofill_plan_items_manual_correction_id", "manual_correction_id"),
        Index("ix_autofill_plan_items_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("autofill_runs.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    scope: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    workbook_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    workbook_path_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sheet_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    field: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    locator: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cell: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    old_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    new_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    value_source: Mapped[str] = mapped_column(String(80), default="rule", nullable=False)
    manual_correction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rule_manual_corrections.id"), nullable=True)
    original_rule_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)


class RuleManualCorrection(TimestampMixin, Base):
    __tablename__ = "rule_manual_corrections"
    __table_args__ = (
        UniqueConstraint("project_id", "rule_kind", "correction_key", name="uq_rule_manual_corrections_project_key"),
        Index("ix_rule_manual_corrections_project_id", "project_id"),
        Index("ix_rule_manual_corrections_rule_kind", "rule_kind"),
        Index("ix_rule_manual_corrections_rule_id", "rule_id"),
        Index("ix_rule_manual_corrections_candidate_key", "candidate_key"),
        Index("ix_rule_manual_corrections_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    workpaper_code: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    workpaper_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    rule_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    candidate_key: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    correction_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sheet_or_section: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    target_field: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    locator: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_type: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    original_payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    manual_correction: Mapped[str] = mapped_column(Text, default="", nullable=False)
    normalized_payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    conflict_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="rule_manual_corrections")
    created_by: Mapped[Optional[User]] = relationship(foreign_keys=[created_by_user_id])
    approved_by: Mapped[Optional[User]] = relationship(foreign_keys=[approved_by_user_id])


class RuleManualCorrectionImport(TimestampMixin, Base):
    __tablename__ = "rule_manual_correction_imports"
    __table_args__ = (
        Index("ix_rule_manual_correction_imports_project_id", "project_id"),
        Index("ix_rule_manual_correction_imports_status", "status"),
        Index("ix_rule_manual_correction_imports_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    file_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result_payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="rule_manual_correction_imports")
    created_by: Mapped[Optional[User]] = relationship()


class AutofillRuleAction(TimestampMixin, Base):
    __tablename__ = "autofill_rule_actions"
    __table_args__ = (
        UniqueConstraint("project_id", "action_key", name="uq_autofill_rule_actions_project_key"),
        Index("ix_autofill_rule_actions_project_id", "project_id"),
        Index("ix_autofill_rule_actions_rule_id", "rule_id"),
        Index("ix_autofill_rule_actions_workpaper_code", "workpaper_code"),
        Index("ix_autofill_rule_actions_status", "action_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    action_key: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    workpaper_code: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    workpaper_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    target_field: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    locator: Mapped[str] = mapped_column(Text, default="", nullable=False)
    action_status: Mapped[str] = mapped_column(String(40), default="pending_confirm", nullable=False)
    action_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_verification_status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    conflict_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    project: Mapped[Project] = relationship(back_populates="autofill_rule_actions")
    created_by: Mapped[Optional[User]] = relationship(foreign_keys=[created_by_user_id])
    updated_by: Mapped[Optional[User]] = relationship(foreign_keys=[updated_by_user_id])


class ReviewRun(TimestampMixin, Base):
    __tablename__ = "review_runs"
    __table_args__ = (
        Index("ix_review_runs_project_id", "project_id"),
        Index("ix_review_runs_workpaper_id", "workpaper_id"),
        Index("ix_review_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    workpaper_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workpapers.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(40), default="auto", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    report_path: Mapped[str] = mapped_column(Text, default="", nullable=False)

    findings: Mapped[list["ReviewFinding"]] = relationship(cascade="all, delete-orphan")


class ReviewFinding(TimestampMixin, Base):
    __tablename__ = "review_findings"
    __table_args__ = (
        Index("ix_review_findings_run_id", "run_id"),
        Index("ix_review_findings_workpaper_id", "workpaper_id"),
        Index("ix_review_findings_workpaper_version_id", "workpaper_version_id"),
        Index("ix_review_findings_resolved_workpaper_version_id", "resolved_workpaper_version_id"),
        Index("ix_review_findings_review_step_id", "review_step_id"),
        Index("ix_review_findings_status", "status"),
        Index("ix_review_findings_severity", "severity"),
        Index("ix_review_findings_assignee_user_id", "assignee_user_id"),
        Index("ix_review_findings_due_date", "due_date"),
        Index("ix_review_findings_issue_no", "issue_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("review_runs.id"), nullable=False)
    workpaper_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workpapers.id", ondelete="SET NULL"), nullable=True)
    workpaper_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workpaper_versions.id", ondelete="SET NULL"), nullable=True)
    resolved_workpaper_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workpaper_versions.id", ondelete="SET NULL"), nullable=True)
    review_step_id: Mapped[Optional[int]] = mapped_column(ForeignKey("review_steps.id", ondelete="SET NULL"), nullable=True)
    issue_no: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    standard_index_code: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    rule_code: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    audit_stage: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    finding_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    issue_step: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    issue_category: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(40), default="medium", nullable=False)
    c22_related: Mapped[bool] = mapped_column(default=False, nullable=False)
    workpaper_file: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target: Mapped[str] = mapped_column(Text, default="", nullable=False)
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    project_reply: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resolution_confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)
    review_stage: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    field_lead: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    project_reviewer: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    assignee_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="", nullable=False)

    assignee: Mapped[Optional[User]] = relationship(foreign_keys=[assignee_user_id])
    created_by: Mapped[Optional[User]] = relationship(foreign_keys=[created_by_user_id])
    histories: Mapped[list["ReviewFindingHistory"]] = relationship(cascade="all, delete-orphan")
    responses: Mapped[list["ReviewFindingResponse"]] = relationship(cascade="all, delete-orphan")


class TrainingWeek(TimestampMixin, Base):
    __tablename__ = "training_weeks"
    __table_args__ = (
        UniqueConstraint("code", name="uq_training_weeks_code"),
        UniqueConstraint("week_no", name="uq_training_weeks_week_no"),
        Index("ix_training_weeks_enabled_sort", "enabled", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    week_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    learning_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    courseware_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    starts_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    questions: Mapped[list["PracticeQuestion"]] = relationship(
        back_populates="training_week", cascade="all, delete-orphan"
    )


class PracticeQuestion(TimestampMixin, Base):
    __tablename__ = "practice_questions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_practice_questions_code"),
        Index("ix_practice_questions_week_sort", "training_week_id", "sort_order"),
        Index("ix_practice_questions_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_week_id: Mapped[int] = mapped_column(ForeignKey("training_weeks.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(40), default="sql", nullable=False)
    project_scope: Mapped[str] = mapped_column(String(40), default="general", nullable=False)
    answer_guidance: Mapped[str] = mapped_column(Text, default="", nullable=False)
    validation_rules_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    training_week: Mapped[TrainingWeek] = relationship(back_populates="questions")
    submissions: Mapped[list["PracticeSubmission"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class PracticeSubmission(TimestampMixin, Base):
    __tablename__ = "practice_submissions"
    __table_args__ = (
        UniqueConstraint("question_id", "user_id", "attempt_no", name="uq_practice_submission_attempt"),
        Index("ix_practice_submissions_question_user", "question_id", "user_id"),
        Index("ix_practice_submissions_status", "status"),
        Index("ix_practice_submissions_submitted_at", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("practice_questions.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sql_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    validation_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    validation_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="", nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    question: Mapped[PracticeQuestion] = relationship(back_populates="submissions")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    reviewer: Mapped[Optional[User]] = relationship(foreign_keys=[reviewer_user_id])


class DevelopmentEmployee(TimestampMixin, Base):
    __tablename__ = "development_employees"
    __table_args__ = (
        UniqueConstraint("code", name="uq_development_employees_code"),
        UniqueConstraint("user_id", name="uq_development_employees_user_id"),
        Index("ix_development_employees_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    current_role: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    hired_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    mentor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    direction: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    half_year_goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    year_goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    advantages: Mapped[str] = mapped_column(Text, default="", nullable=False)
    weaknesses: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_focus: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recent_issues: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mentor_observation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    development_intent: Mapped[str] = mapped_column(Text, default="", nullable=False)
    questionnaire_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)

    user: Mapped[Optional[User]] = relationship(foreign_keys=[user_id])
    mentor: Mapped[Optional[User]] = relationship(foreign_keys=[mentor_user_id])
    competency_scores: Mapped[list["EmployeeCompetency"]] = relationship(cascade="all, delete-orphan")
    plans: Mapped[list["DevelopmentPlan"]] = relationship(cascade="all, delete-orphan")


class CompetencyDimension(TimestampMixin, Base):
    __tablename__ = "competency_dimensions"
    __table_args__ = (UniqueConstraint("code", name="uq_competency_dimensions_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class EmployeeCompetency(TimestampMixin, Base):
    __tablename__ = "employee_competencies"
    __table_args__ = (
        Index("ix_employee_competencies_employee_date", "employee_id", "assessed_on"),
        Index("ix_employee_competencies_dimension_date", "competency_id", "assessed_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency_dimensions.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    assessed_on: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="manual", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    assessor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    competency: Mapped[CompetencyDimension] = relationship()
    assessor: Mapped[Optional[User]] = relationship()


class DevelopmentPlan(TimestampMixin, Base):
    __tablename__ = "development_plans"
    __table_args__ = (Index("ix_development_plans_employee_status", "employee_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(40), default="annual", nullable=False)
    starts_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ends_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    half_year_goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    year_goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)

    monthly_plans: Mapped[list["MonthlyPlan"]] = relationship(cascade="all, delete-orphan")


class MonthlyPlan(TimestampMixin, Base):
    __tablename__ = "monthly_plans"
    __table_args__ = (
        UniqueConstraint("development_plan_id", "month_no", name="uq_monthly_plans_plan_month"),
        Index("ix_monthly_plans_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    development_plan_id: Mapped[int] = mapped_column(ForeignKey("development_plans.id", ondelete="CASCADE"), nullable=False)
    month_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    month_goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    generation_basis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expected_project: Mapped[str] = mapped_column(Text, default="", nullable=False)
    starts_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ends_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    generated_by: Mapped[str] = mapped_column(String(80), default="manual", nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    weekly_tasks: Mapped[list["WeeklyTask"]] = relationship(cascade="all, delete-orphan")


class WeeklyTask(TimestampMixin, Base):
    __tablename__ = "weekly_tasks"
    __table_args__ = (
        Index("ix_weekly_tasks_month_week", "monthly_plan_id", "week_no"),
        Index("ix_weekly_tasks_status_due", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monthly_plan_id: Mapped[int] = mapped_column(ForeignKey("monthly_plans.id", ondelete="CASCADE"), nullable=False)
    week_no: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(String(240), nullable=False)
    learning_content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    exercise_case: Mapped[str] = mapped_column(Text, default="", nullable=False)
    deliverable: Mapped[str] = mapped_column(Text, default="", nullable=False)
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="not_started", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    owner: Mapped[Optional[User]] = relationship()
    exercises: Mapped[list["DevelopmentExercise"]] = relationship(cascade="all, delete-orphan")


class DevelopmentExercise(TimestampMixin, Base):
    __tablename__ = "development_exercises"
    __table_args__ = (UniqueConstraint("code", name="uq_development_exercises_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weekly_task_id: Mapped[int] = mapped_column(ForeignKey("weekly_tasks.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    exercise_type: Mapped[str] = mapped_column(String(40), default="case", nullable=False)
    topic: Mapped[str] = mapped_column(String(240), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(40), default="medium", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    competency_codes_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)


class DevelopmentExerciseSubmission(TimestampMixin, Base):
    __tablename__ = "development_exercise_submissions"
    __table_args__ = (
        UniqueConstraint("exercise_id", "employee_id", "attempt_no", name="uq_development_submission_attempt"),
        Index("ix_development_submissions_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("development_exercises.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attachment_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)
    used_ai: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DevelopmentReview(TimestampMixin, Base):
    __tablename__ = "development_reviews"
    __table_args__ = (Index("ix_development_reviews_employee_status", "employee_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False)
    submission_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_exercise_submissions.id", ondelete="SET NULL"), nullable=True)
    weekly_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("weekly_tasks.id", ondelete="SET NULL"), nullable=True)
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="", nullable=False)
    passed: Mapped[bool] = mapped_column(default=False, nullable=False)
    needs_redo: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DevelopmentIssue(TimestampMixin, Base):
    __tablename__ = "development_issues"
    __table_args__ = (
        Index("ix_development_issues_employee_status", "employee_id", "status"),
        Index("ix_development_issues_fingerprint", "employee_id", "fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False)
    review_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_reviews.id", ondelete="SET NULL"), nullable=True)
    source: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    issue_type: Mapped[str] = mapped_column(String(80), default="method", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(40), default="medium", nullable=False)
    competency_code: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    improvement_requirement: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    repeat_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_seen_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    verification_method: Mapped[str] = mapped_column(Text, default="", nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DevelopmentLearningRecord(TimestampMixin, Base):
    __tablename__ = "development_learning_records"
    __table_args__ = (Index("ix_development_learning_employee_date", "employee_id", "training_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False)
    weekly_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("weekly_tasks.id", ondelete="SET NULL"), nullable=True)
    topic: Mapped[str] = mapped_column(String(240), nullable=False)
    material_reference: Mapped[str] = mapped_column(Text, default="", nullable=False)
    training_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    attended: Mapped[bool] = mapped_column(default=False, nullable=False)
    self_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mentor_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class MonthlyAssessment(TimestampMixin, Base):
    __tablename__ = "monthly_assessments"
    __table_args__ = (UniqueConstraint("monthly_plan_id", name="uq_monthly_assessments_plan"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monthly_plan_id: Mapped[int] = mapped_column(ForeignKey("monthly_plans.id", ondelete="CASCADE"), nullable=False)
    employee_self_review: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mentor_review: Mapped[str] = mapped_column(Text, default="", nullable=False)
    completion_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    exercise_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    unfamiliar_case_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    project_performance_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    initiative_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    competency_changes_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    unresolved_issues_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    next_month_suggestion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    assessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PlanAdjustment(TimestampMixin, Base):
    __tablename__ = "plan_adjustments"
    __table_args__ = (Index("ix_plan_adjustments_month_time", "monthly_plan_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monthly_plan_id: Mapped[int] = mapped_column(ForeignKey("monthly_plans.id", ondelete="CASCADE"), nullable=False)
    changed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    after_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    changed_by: Mapped[Optional[User]] = relationship()


# Personnel development models are intentionally kept separate from the
# existing project ``Task`` and learning-course ``TrainingWeek`` tables.  The
# project task has a mandatory project_id, while the course week is a shared
# catalogue item; neither can represent an employee-specific plan hierarchy.
class DevelopmentTrainingPlan(TimestampMixin, Base):
    __tablename__ = "development_training_plans"
    __table_args__ = (
        Index("ix_development_training_plans_employee_status", "employee_id", "status"),
        Index("ix_development_training_plans_period", "period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Snapshot fields preserve the employee identity used when a plan was imported.
    employee_code: Mapped[str] = mapped_column(String(80), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    source_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    plan_type: Mapped[str] = mapped_column(String(80), default="special_training", nullable=False)
    period: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    overall_goal: Mapped[str] = mapped_column(Text, default="", nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    mentor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    employee: Mapped[User] = relationship(foreign_keys=[employee_id])
    mentor: Mapped[Optional[User]] = relationship(foreign_keys=[mentor_id])
    weeks: Mapped[list["DevelopmentTrainingWeek"]] = relationship(cascade="all, delete-orphan")
    assessments: Mapped[list["DevelopmentMonthlyAssessment"]] = relationship(cascade="all, delete-orphan")


class DevelopmentTrainingWeek(TimestampMixin, Base):
    __tablename__ = "development_training_weeks"
    __table_args__ = (
        UniqueConstraint("training_plan_id", "week_no", name="uq_development_training_weeks_plan_no"),
        Index("ix_development_training_weeks_plan_sort", "training_plan_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_plan_id: Mapped[int] = mapped_column(ForeignKey("development_training_plans.id", ondelete="CASCADE"), nullable=False)
    week_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expected_deliverable: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    tasks: Mapped[list["DevelopmentTrainingTask"]] = relationship(cascade="all, delete-orphan")


class DevelopmentTrainingTask(TimestampMixin, Base):
    __tablename__ = "development_training_tasks"
    __table_args__ = (
        UniqueConstraint("training_week_id", "task_code", name="uq_development_training_tasks_week_code"),
        Index("ix_development_training_tasks_week_sort", "training_week_id", "sort_order"),
        Index("ix_development_training_tasks_status_due", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_week_id: Mapped[int] = mapped_column(ForeignKey("development_training_weeks.id", ondelete="CASCADE"), nullable=False)
    task_code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    purpose: Mapped[str] = mapped_column(Text, default="", nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), default="learning", nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prerequisite_task_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    completion_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    self_check_questions: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    submission_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    submission_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    submission_title: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    submission_requirements: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mentor_review_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="not_started", nullable=False)

    materials: Mapped[list["DevelopmentLearningMaterial"]] = relationship(cascade="all, delete-orphan")
    submissions: Mapped[list["DevelopmentSubmission"]] = relationship(cascade="all, delete-orphan")
    blockers: Mapped[list["DevelopmentBlocker"]] = relationship(cascade="all, delete-orphan")


class DevelopmentLearningMaterialRead(TimestampMixin, Base):
    __tablename__ = "development_learning_material_reads"
    __table_args__ = (
        UniqueConstraint("material_id", "employee_id", name="uq_development_material_reads_employee"),
        Index("ix_development_learning_material_reads_employee", "employee_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("development_learning_materials.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    material: Mapped["DevelopmentLearningMaterial"] = relationship()
    employee: Mapped[User] = relationship()


class DevelopmentLearningMaterial(TimestampMixin, Base):
    __tablename__ = "development_learning_materials"
    __table_args__ = (
        Index("ix_development_learning_materials_task_sort", "task_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    material_type: Mapped[str] = mapped_column(String(40), nullable=False)
    course_scope: Mapped[str] = mapped_column(String(20), default="personal", nullable=False)
    url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DevelopmentTaskNote(TimestampMixin, Base):
    __tablename__ = "development_task_notes"
    __table_args__ = (UniqueConstraint("task_id", "employee_id", name="uq_development_task_notes_task_employee"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)


class DevelopmentSubmission(TimestampMixin, Base):
    __tablename__ = "development_submissions"
    __table_args__ = (
        UniqueConstraint("task_id", "employee_id", "version", name="uq_development_submissions_task_employee_version"),
        Index("ix_development_submissions_employee_submitted", "employee_id", "submitted_at"),
        Index("ix_development_submissions_task_status", "task_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    submission_type: Mapped[str] = mapped_column(String(40), default="assignment", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attachment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    self_check_answers: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="submitted", nullable=False)

    employee: Mapped[User] = relationship()
    reviews: Mapped[list["DevelopmentSubmissionReview"]] = relationship(cascade="all, delete-orphan")


class DevelopmentSubmissionReview(TimestampMixin, Base):
    __tablename__ = "development_submission_reviews"
    __table_args__ = (
        Index("ix_development_submission_reviews_submission_time", "submission_id", "reviewed_at"),
        Index("ix_development_submission_reviews_reviewer", "reviewer_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("development_submissions.id", ondelete="CASCADE"), nullable=False)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comments: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    reviewer: Mapped[User] = relationship()


class DevelopmentBlocker(TimestampMixin, Base):
    __tablename__ = "development_blockers"
    __table_args__ = (
        Index("ix_development_blockers_employee_status", "employee_id", "status"),
        Index("ix_development_blockers_task_status", "task_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_facts: Mapped[str] = mapped_column(Text, default="", nullable=False)
    materials_checked: Mapped[str] = mapped_column(Text, default="", nullable=False)
    initial_judgment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attempted_solutions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    missing_information: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mentor_question: Mapped[str] = mapped_column(Text, default="", nullable=False)
    blocker_type: Mapped[str] = mapped_column(String(80), default="general", nullable=False)
    self_analysis_complete: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    mentor_response: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resolution_action: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    resolved_by: Mapped[Optional[User]] = relationship(foreign_keys=[resolved_by_user_id])


class DevelopmentMonthlyAssessment(TimestampMixin, Base):
    __tablename__ = "development_monthly_assessments"
    __table_args__ = (
        UniqueConstraint("training_plan_id", "period", name="uq_development_monthly_assessments_plan_period"),
        Index("ix_development_monthly_assessments_employee_period", "employee_id", "period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_plan_id: Mapped[int] = mapped_column(ForeignKey("development_training_plans.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    total_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    assessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    thresholds_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    dimensions: Mapped[list["DevelopmentAssessmentDimension"]] = relationship(cascade="all, delete-orphan")


class DevelopmentAssessmentDimension(TimestampMixin, Base):
    __tablename__ = "development_assessment_dimensions"
    __table_args__ = (
        UniqueConstraint("assessment_id", "dimension_code", name="uq_development_assessment_dimensions_code"),
        Index("ix_development_assessment_dimensions_assessment_sort", "assessment_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("development_monthly_assessments.id", ondelete="CASCADE"), nullable=False)
    dimension_code: Mapped[str] = mapped_column(String(80), nullable=False)
    dimension_name: Mapped[str] = mapped_column(String(160), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    comments: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DevelopmentLearningEvent(TimestampMixin, Base):
    """Append-only learner telemetry used later for personal monthly reviews."""
    __tablename__ = "development_learning_events"
    __table_args__ = (
        Index("ix_development_learning_events_employee_time", "employee_id", "occurred_at"),
        Index("ix_development_learning_events_plan_type_time", "training_plan_id", "event_type", "occurred_at"),
        Index("ix_development_learning_events_task_type_time", "task_id", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    training_plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_training_plans.id", ondelete="SET NULL"), nullable=True)
    training_week_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_training_weeks.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_training_tasks.id", ondelete="SET NULL"), nullable=True)
    submission_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_submissions.id", ondelete="SET NULL"), nullable=True)
    material_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_learning_materials.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    skill_tag: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    competency_code: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="system", nullable=False)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    employee: Mapped[User] = relationship(foreign_keys=[employee_id])


class DevelopmentQuizItemResult(TimestampMixin, Base):
    """Per-question attempt history, including failed gates that never became a submission."""
    __tablename__ = "development_quiz_item_results"
    __table_args__ = (
        UniqueConstraint("employee_id", "task_id", "attempt_no", "question_index", name="uq_development_quiz_results_attempt"),
        Index("ix_development_quiz_results_employee_task", "employee_id", "task_id", "occurred_at"),
        Index("ix_development_quiz_results_knowledge", "employee_id", "knowledge_key", "occurred_at"),
        Index("ix_development_quiz_results_plan_skill", "training_plan_id", "skill_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    training_plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_training_plans.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False)
    submission_id: Mapped[Optional[int]] = mapped_column(ForeignKey("development_submissions.id", ondelete="SET NULL"), nullable=True)
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question_fingerprint: Mapped[str] = mapped_column(String(40), nullable=False)
    knowledge_key: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    skill_tag: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    competency_code: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    submitted_answer_json: Mapped[str] = mapped_column(Text, default="null", nullable=False)
    correct_answer_json: Mapped[str] = mapped_column(Text, default="null", nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_gate: Mapped[bool] = mapped_column(default=False, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    employee: Mapped[User] = relationship(foreign_keys=[employee_id])


class ReviewFindingHistory(TimestampMixin, Base):
    __tablename__ = "review_finding_histories"
    __table_args__ = (
        Index("ix_review_finding_histories_finding_id", "finding_id"),
        Index("ix_review_finding_histories_operator_user_id", "operator_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("review_findings.id"), nullable=False)
    operator_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    old_status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    new_status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    operator: Mapped[Optional[User]] = relationship(foreign_keys=[operator_user_id])


class ReviewFindingResponse(TimestampMixin, Base):
    __tablename__ = "review_finding_responses"
    __table_args__ = (
        UniqueConstraint("finding_id", "round_no", name="uq_review_finding_responses_finding_round"),
        Index("ix_review_finding_responses_finding_id", "finding_id"),
        Index("ix_review_finding_responses_responder_user_id", "responder_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("review_findings.id", ondelete="CASCADE"), nullable=False)
    responder_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    attachment: Mapped[str] = mapped_column(Text, default="", nullable=False)

    responder: Mapped[Optional[User]] = relationship(foreign_keys=[responder_user_id])


class ReviewStep(TimestampMixin, Base):
    __tablename__ = "review_steps"
    __table_args__ = (
        UniqueConstraint("workpaper_id", "sequence_no", name="uq_review_steps_workpaper_sequence"),
        Index("ix_review_steps_workpaper_id", "workpaper_id"),
        Index("ix_review_steps_workpaper_version_id", "workpaper_version_id"),
        Index("ix_review_steps_reviewer_user_id", "reviewer_user_id"),
        Index("ix_review_steps_status", "status"),
        Index("ix_review_steps_due_date", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("workpapers.id"), nullable=False)
    workpaper_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workpaper_versions.id", ondelete="SET NULL"), nullable=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewer_role_code: Mapped[str] = mapped_column(String(120), nullable=False)
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    round_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="waiting", nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    entered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sla_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    reviewer: Mapped[Optional[User]] = relationship(foreign_keys=[reviewer_user_id])
    histories: Mapped[list["ReviewStepHistory"]] = relationship(cascade="all, delete-orphan")


class ReviewStepHistory(TimestampMixin, Base):
    __tablename__ = "review_step_histories"
    __table_args__ = (
        Index("ix_review_step_histories_step_id", "step_id"),
        Index("ix_review_step_histories_workpaper_version_id", "workpaper_version_id"),
        Index("ix_review_step_histories_operator_user_id", "operator_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("review_steps.id", ondelete="CASCADE"), nullable=False)
    workpaper_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workpaper_versions.id", ondelete="SET NULL"), nullable=True)
    operator_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    round_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    old_status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    new_status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)

    operator: Mapped[Optional[User]] = relationship(foreign_keys=[operator_user_id])


class FeatureModule(TimestampMixin, Base):
    __tablename__ = "feature_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


class RoleFeaturePermission(TimestampMixin, Base):
    __tablename__ = "role_feature_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "feature_module_id", name="uq_role_feature_permissions_role_module"),
        Index("ix_role_feature_permissions_role_id", "role_id"),
        Index("ix_role_feature_permissions_feature_module_id", "feature_module_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    feature_module_id: Mapped[int] = mapped_column(ForeignKey("feature_modules.id"), nullable=False)
    can_view: Mapped[bool] = mapped_column(default=True, nullable=False)
    can_edit: Mapped[bool] = mapped_column(default=False, nullable=False)
    can_manage: Mapped[bool] = mapped_column(default=False, nullable=False)

    role: Mapped[Role] = relationship()
    feature_module: Mapped[FeatureModule] = relationship()


class WorkpaperTemplate(TimestampMixin, Base):
    __tablename__ = "workpaper_templates"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_workpaper_templates_code_version"),
        Index("ix_workpaper_templates_code", "code"),
        Index("ix_workpaper_templates_enabled", "default_enabled"),
        Index("ix_workpaper_templates_source_path_hash", "source_path_hash"),
        Index("ix_workpaper_templates_applicable_year", "applicable_year"),
        Index("ix_workpaper_templates_is_latest", "is_latest"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    stage: Mapped[str] = mapped_column(String(80), default="execution", nullable=False)
    source_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_path_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version: Mapped[str] = mapped_column(String(40), default="default", nullable=False)
    applicable_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    update_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_latest: Mapped[bool] = mapped_column(default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    default_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ImportBatch(TimestampMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        Index("ix_import_batches_source_type", "source_type"),
        Index("ix_import_batches_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_name: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    source_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_path_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dry_run: Mapped[bool] = mapped_column(default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    records: Mapped[list["ImportRecord"]] = relationship(cascade="all, delete-orphan")
    errors: Mapped[list["ImportErrorRecord"]] = relationship(cascade="all, delete-orphan")


class ImportRecord(TimestampMixin, Base):
    __tablename__ = "import_records"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_key", name="uq_import_records_batch_source_key"),
        Index("ix_import_records_batch_id", "batch_id"),
        Index("ix_import_records_source_key", "source_key"),
        Index("ix_import_records_fingerprint", "fingerprint"),
        Index("ix_import_records_target", "target_table", "target_id"),
        Index("ix_import_records_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), nullable=False)
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_row_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_table: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class ImportErrorRecord(TimestampMixin, Base):
    __tablename__ = "import_errors"
    __table_args__ = (
        Index("ix_import_errors_batch_id", "batch_id"),
        Index("ix_import_errors_record_id", "record_id"),
        Index("ix_import_errors_severity", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), nullable=False)
    record_id: Mapped[Optional[int]] = mapped_column(ForeignKey("import_records.id"), nullable=True)
    severity: Mapped[str] = mapped_column(String(40), default="error", nullable=False)
    code: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


@event.listens_for(Client, "before_insert")
@event.listens_for(Client, "before_update")
def sync_client_normalized_name(mapper, connection, target: Client) -> None:
    target.normalized_entity_name = normalized_text_key(target.entity_name) or None


@event.listens_for(Workpaper, "before_insert")
@event.listens_for(Workpaper, "before_update")
def sync_workpaper_file_hash(mapper, connection, target: Workpaper) -> None:
    target.file_path_hash = nullable_hash(target.file_path)


@event.listens_for(Attachment, "before_insert")
@event.listens_for(Attachment, "before_update")
def sync_attachment_file_hash(mapper, connection, target: Attachment) -> None:
    target.file_path_hash = nullable_hash(target.file_path)


@event.listens_for(AutofillPlanItem, "before_insert")
@event.listens_for(AutofillPlanItem, "before_update")
def sync_autofill_workbook_hash(mapper, connection, target: AutofillPlanItem) -> None:
    target.workbook_path_hash = nullable_hash(target.workbook_path)


@event.listens_for(WorkpaperTemplate, "before_insert")
@event.listens_for(WorkpaperTemplate, "before_update")
def sync_template_source_hash(mapper, connection, target: WorkpaperTemplate) -> None:
    target.source_path_hash = nullable_hash(target.source_path)


@event.listens_for(ImportBatch, "before_insert")
@event.listens_for(ImportBatch, "before_update")
def sync_import_batch_source_hash(mapper, connection, target: ImportBatch) -> None:
    target.source_path_hash = nullable_hash(target.source_path)
