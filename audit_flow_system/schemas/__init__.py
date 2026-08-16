from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

class OrmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RoleIn(BaseModel):
    code: str
    name: str
    rank: int = 0
    can_review: bool = False
    description: str = ""


class UserIn(BaseModel):
    username: str
    display_name: str
    email: str = ""
    phone: str = ""
    password: str = ""
    status: str = "active"
    role_id: Optional[int] = None


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordPolicyIn(BaseModel):
    min_length: int = Field(default=8, ge=8, le=64)
    require_digit: bool = True
    require_upper: bool = True
    require_lower: bool = True
    require_special: bool = True
    expiry_days: int = Field(default=180, ge=1, le=3650)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ClientIn(BaseModel):
    entity_name: str
    finance_director_name: str = ""
    finance_director_phone: str = ""
    finance_director_email: str = ""
    description: str = ""


class ClientITContactIn(BaseModel):
    name: str
    title: str = ""
    department: str = ""
    phone: str = ""
    email: str = ""
    responsibility: str = ""


class ProjectIn(BaseModel):
    name: str
    code: str = ""
    oa_project_no: str = ""
    ims_project_no: str = ""
    client_id: Optional[int] = None
    entity_name: str = ""
    audit_year: Optional[int] = None
    audit_scope_start: Optional[date] = None
    audit_scope_end: Optional[date] = None
    status: str = "planning"
    project_leader_user_id: Optional[int] = None
    manager_user_id: Optional[int] = None
    quality_reviewer_user_id: Optional[int] = None
    field_leader_user_id: Optional[int] = None
    first_partner_name: str = ""
    first_partner_email: str = ""
    first_partner_phone: str = ""
    second_partner_name: str = ""
    second_partner_email: str = ""
    second_partner_phone: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    prior_project_id: Optional[int] = None
    project_root: str = ""
    description: str = ""


class ContactIn(BaseModel):
    name: str
    title: str = ""
    department: str = ""
    phone: str = ""
    email: str = ""
    responsibility: str = ""


class MemberIn(BaseModel):
    user_id: int
    role_on_project: str = ""
    module: str = ""
    workload: str = ""


class DocumentRequestUploadIn(BaseModel):
    file_paths: list[str] = Field(default_factory=list)


class DueDateIn(BaseModel):
    due_date: Optional[date] = None


class TaskIn(BaseModel):
    project_id: int
    module: str = "ITGC"
    name: str
    owner_user_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    progress: int = Field(default=0, ge=0, le=100)
    status: str = "open"


class WorkpaperIn(BaseModel):
    project_id: int
    code: str
    name: str
    stage: str = "execution"
    file_path: str = ""
    source_workpaper_id: Optional[int] = None
    status: str = "draft"
    preparer_user_id: Optional[int] = None
    year_updated: bool = False
    extracted_fields: dict[str, Any] = Field(default_factory=dict)


class AttachmentIn(BaseModel):
    project_id: int
    workpaper_id: Optional[int] = None
    index_no: str = ""
    title: str
    file_path: str = ""
    file_type: str = ""
    referenced_in: str = ""
    status: str = "active"


class AttachmentScanIn(BaseModel):
    dry_run: bool = True
    subdir: str = ""


class AttachmentReferenceScanIn(BaseModel):
    dry_run: bool = True


class AutomationRuleIn(BaseModel):
    code: str
    name: str
    category: str = ""
    severity: str = "medium"
    enabled: bool = True
    description: str = ""


class InitFromPriorIn(BaseModel):
    prior_project_id: Optional[int] = None
    copy_files: bool = True


class ReviewRunIn(BaseModel):
    project_id: int
    workpaper_id: Optional[int] = None
    use_external_rules: bool = False


class ReviewFindingIn(BaseModel):
    project_id: Optional[int] = None
    run_id: Optional[int] = None
    rule_code: str = "MANUAL"
    severity: str = "medium"
    target: str = ""
    issue: str
    evidence: str = ""
    status: str = "open"
    assignee_user_id: Optional[int] = None
    due_date: Optional[date] = None
    review_comment: str = ""


class ReviewFindingPatchIn(BaseModel):
    rule_code: Optional[str] = None
    severity: Optional[str] = None
    target: Optional[str] = None
    issue: Optional[str] = None
    evidence: Optional[str] = None
    status: Optional[str] = None
    assignee_user_id: Optional[int] = None
    due_date: Optional[date] = None
    review_comment: Optional[str] = None
    history_comment: Optional[str] = None


class ReviewFindingReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=10000)


class ReviewFindingAssignIn(BaseModel):
    assignee_user_id: int
    due_date: date
    assignment_comment: str = ""


class AutofillPlanIn(BaseModel):
    scope: Optional[str] = None
    apply: bool = False


class AutofillRuleActionIn(BaseModel):
    rule_id: str = ""
    workpaper_code: str = ""
    workpaper_name: str = ""
    target_field: str = ""
    locator: str = ""
    action_status: str = "pending_confirm"
    action_note: str = ""
    source_verification_status: str = ""
    conflict_message: str = ""


class AutofillRuleActionPatchIn(BaseModel):
    action_status: Optional[str] = None
    action_note: Optional[str] = None
    source_verification_status: Optional[str] = None
    conflict_message: Optional[str] = None


class ReviewDecisionIn(BaseModel):
    reviewer_user_id: Optional[int] = None
    comment: str = ""


class PracticeSubmissionIn(BaseModel):
    answer_text: str = Field(default="", max_length=50000)
    sql_text: str = Field(default="", max_length=50000)


class PracticeValidateIn(BaseModel):
    sql_text: str = Field(default="", max_length=50000)


class PracticeExecuteIn(BaseModel):
    sql_text: str = Field(default="", max_length=50000)


class PracticeReviewIn(BaseModel):
    score: int = Field(ge=0, le=200)
    feedback: str = Field(default="", max_length=20000)


class C21IssueOut(BaseModel):
    project_id: int
    project_name: str = ""
    workpaper_id: Optional[int] = None
    workpaper_code: str = ""
    source: str = ""
    row_no: int = 0
    issue_no: str = ""
    title: str = ""
    description: str = ""
    severity: str = ""
    control_code: str = ""
    recommendation: str = ""
    owner: str = ""
    status: str = ""
    raw_values: list[str] = Field(default_factory=list)


class ProjectC21IssuesOut(BaseModel):
    project_id: int
    project_name: str = ""
    workpaper_id: Optional[int] = None
    workpaper_code: str = ""
    workpaper_name: str = ""
    file_path: str = ""
    status: str = ""
    error: str = ""
    issues: list[dict[str, Any]] = Field(default_factory=list)


class ClientIssuesOut(BaseModel):
    id: int
    entity_name: str = ""
    project_count: int = 0
    issue_count: int = 0
    issues: list[C21IssueOut] = Field(default_factory=list)
    projects: list[ProjectC21IssuesOut] = Field(default_factory=list)


class WorkpaperTreeNodeOut(BaseModel):
    id: str
    type: str
    label: str
    workpaper_id: Optional[int] = None
    attachment_id: Optional[int] = None
    index_no: str = ""
    code: str = ""
    name: str = ""
    stage: str = ""
    status: str = ""
    file_type: str = ""
    file_path: str = ""
    referenced_in: str = ""
    sheet: str = ""
    children: list["WorkpaperTreeNodeOut"] = Field(default_factory=list)


class WorkpaperPreviewOut(BaseModel):
    id: int
    project_id: int
    code: str = ""
    name: str = ""
    stage: str = ""
    file_path: str = ""
    status: str = ""
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    file_exists: bool = False
    file_type: str = ""
    preview_text: str = ""
    lines: list[str] = Field(default_factory=list)
    sheets: list[str] = Field(default_factory=list)
    sheet_sections: list[dict[str, Any]] = Field(default_factory=list)
    recognition_note: str = ""
    preparer_name: str = ""
    prepared_at: Optional[datetime] = None
    reviewer_name: str = ""
    reviewed_at: Optional[datetime] = None
    review_started: bool = False
    review_steps: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""
