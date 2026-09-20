from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

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
    min_length: int = Field(default=6, ge=1, le=64)
    require_digit: bool = True
    require_upper: bool = False
    require_special: bool = False


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
    project_type: str = "it_audit"
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
    quality_reviewer_user_ids: list[int] = Field(default_factory=list)
    field_leader_user_id: Optional[int] = None
    director_user_id: Optional[int] = None
    partner_user_id: Optional[int] = None
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


class HomeProjectMemberWorkloadIn(BaseModel):
    member_id: int
    workload: str = Field(default="", max_length=120)


class HomeProjectUpdateIn(BaseModel):
    """Editable directory fields exposed from the homepage project detail."""
    name: Optional[str] = None
    code: Optional[str] = None
    oa_project_no: Optional[str] = None
    ims_project_no: Optional[str] = None
    entity_name: Optional[str] = None
    audit_year: Optional[int] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    audit_scope_start: Optional[date] = None
    audit_scope_end: Optional[date] = None
    project_leader_user_id: Optional[int] = None
    manager_user_id: Optional[int] = None
    field_leader_user_id: Optional[int] = None
    quality_reviewer_user_id: Optional[int] = None
    director_user_id: Optional[int] = None
    partner_user_id: Optional[int] = None
    member_workloads: Optional[list[HomeProjectMemberWorkloadIn]] = None
    department: Optional[str] = None
    scope_description: Optional[str] = None
    business_revenue: Optional[str] = None


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


class HomeProjectMemberBatchIn(BaseModel):
    items: list[MemberIn] = Field(default_factory=list, max_length=100)


class HomeProjectClaimApprovalIn(BaseModel):
    claim_ids: list[int] = Field(default_factory=list, min_length=1, max_length=100)


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


class WorkpaperPatchIn(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    stage: Optional[str] = None
    preparer_user_id: Optional[int] = None
    year_updated: Optional[bool] = None


class WorkpaperSubmitIn(BaseModel):
    """Optional first reviewer selected by the preparer for the first submission."""
    next_reviewer_user_id: Optional[int] = None


class BatchWorkpaperSubmitIn(BaseModel):
    workpaper_ids: list[int] = Field(min_length=1, max_length=100)
    next_reviewer_user_id: int


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
    review_engine: Literal["rules", "external_rules", "deepseek"] = "rules"


class ReviewFindingIn(BaseModel):
    project_id: Optional[int] = None
    run_id: Optional[int] = None
    workpaper_id: Optional[int] = None
    review_step_id: Optional[int] = None
    issue_no: str = ""
    standard_index_code: str = ""
    source: str = "manual"
    rule_code: str = "MANUAL"
    audit_stage: str = ""
    finding_type: str = ""
    issue_step: str = ""
    issue_category: str = ""
    severity: str = "medium"
    c22_related: bool = False
    workpaper_file: str = ""
    location: str = ""
    target: str = ""
    issue: str
    evidence: str = ""
    recommendation: str = ""
    project_reply: str = ""
    resolution_confirmed: bool = False
    review_stage: str = ""
    field_lead: str = ""
    project_reviewer: str = ""
    assignee_user_id: Optional[int] = None
    status: str = "open"
    review_comment: str = ""


class ReviewFindingPatchIn(BaseModel):
    issue_no: Optional[str] = None
    standard_index_code: Optional[str] = None
    source: Optional[str] = None
    rule_code: Optional[str] = None
    audit_stage: Optional[str] = None
    finding_type: Optional[str] = None
    issue_step: Optional[str] = None
    issue_category: Optional[str] = None
    severity: Optional[str] = None
    c22_related: Optional[bool] = None
    workpaper_file: Optional[str] = None
    location: Optional[str] = None
    target: Optional[str] = None
    issue: Optional[str] = None
    evidence: Optional[str] = None
    recommendation: Optional[str] = None
    project_reply: Optional[str] = None
    resolution_confirmed: Optional[bool] = None
    review_stage: Optional[str] = None
    field_lead: Optional[str] = None
    project_reviewer: Optional[str] = None
    status: Optional[str] = None
    review_comment: Optional[str] = None


class ReviewFindingResponseIn(BaseModel):
    response_text: str = Field(min_length=1)
    attachment: str = ""


class ReviewFindingDecisionIn(BaseModel):
    result: Literal["changes_requested", "closed", "reopened"]
    comment: str = Field(min_length=1)


class AutofillPlanIn(BaseModel):
    scope: Optional[str] = None
    apply: bool = False


class AutofillRuleActionIn(BaseModel):
    rule_id: str = ""
    workpaper_code: str = ""
    workpaper_name: str = ""
    target_field: str = ""
    locator: str = ""


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
    action_status: str = "pending_confirm"
    action_note: str = ""
    source_verification_status: str = ""
    conflict_message: str = ""


class DevelopmentEmployeeIn(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    user_id: Optional[int] = None
    current_role: str = ""
    hired_on: Optional[date] = None
    mentor_user_id: Optional[int] = None
    direction: str = ""
    half_year_goal: str = ""
    year_goal: str = ""
    advantages: str = ""
    weaknesses: str = ""
    current_focus: str = ""
    recent_issues: str = ""
    mentor_observation: str = ""
    development_intent: str = ""
    status: str = "active"


class DevelopmentEmployeePatchIn(BaseModel):
    name: Optional[str] = None
    user_id: Optional[int] = None
    current_role: Optional[str] = None
    hired_on: Optional[date] = None
    mentor_user_id: Optional[int] = None
    direction: Optional[str] = None
    half_year_goal: Optional[str] = None
    year_goal: Optional[str] = None
    advantages: Optional[str] = None
    weaknesses: Optional[str] = None
    current_focus: Optional[str] = None
    recent_issues: Optional[str] = None
    mentor_observation: Optional[str] = None
    development_intent: Optional[str] = None
    status: Optional[str] = None


class CompetencyAssessmentIn(BaseModel):
    competency_code: str
    score: float = Field(ge=1, le=5)
    assessed_on: date
    source: str = "manual"
    note: str = ""


class DevelopmentPlanIn(BaseModel):
    employee_id: int
    title: str
    plan_type: str = "annual"
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    half_year_goal: str = ""
    year_goal: str = ""
    status: str = "draft"
    source_type: str = "manual"
    source_reference: str = ""


class MonthlyPlanIn(BaseModel):
    development_plan_id: int
    month_no: int = Field(ge=1, le=24)
    title: str
    month_goal: str = ""
    generation_basis: str = ""
    rationale: str = ""
    expected_project: str = ""
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    status: str = "draft"
    generated_by: str = "manual"


class WeeklyTaskIn(BaseModel):
    monthly_plan_id: int
    week_no: int = Field(ge=1, le=6)
    topic: str
    learning_content: str = ""
    exercise_case: str = ""
    deliverable: str = ""
    acceptance_criteria: str = ""
    owner_user_id: Optional[int] = None
    due_date: Optional[date] = None
    status: str = "not_started"
    progress: int = Field(default=0, ge=0, le=100)


class WeeklyTaskPatchIn(BaseModel):
    topic: Optional[str] = None
    learning_content: Optional[str] = None
    exercise_case: Optional[str] = None
    deliverable: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    owner_user_id: Optional[int] = None
    due_date: Optional[date] = None
    status: Optional[str] = None
    progress: Optional[int] = Field(default=None, ge=0, le=100)


class DevelopmentExerciseIn(BaseModel):
    weekly_task_id: int
    code: str
    exercise_type: str = "case"
    topic: str
    difficulty: str = "medium"
    prompt: str = ""
    acceptance_criteria: str = ""
    competency_codes: list[str] = Field(default_factory=list)
    due_at: Optional[datetime] = None


class DevelopmentSubmissionIn(BaseModel):
    exercise_id: int
    employee_id: int
    content: str = ""
    attachment_reference: str = ""
    used_ai: bool = False
    submit: bool = True


class DevelopmentReviewIn(BaseModel):
    employee_id: int
    submission_id: Optional[int] = None
    weekly_task_id: Optional[int] = None
    score: Optional[float] = Field(default=None, ge=0, le=100)
    feedback: str = ""
    passed: bool = False
    needs_redo: bool = False
    status: str = "completed"


class DevelopmentIssueIn(BaseModel):
    employee_id: int
    review_id: Optional[int] = None
    source: str = ""
    issue_type: str = "method"
    description: str
    severity: str = "medium"
    competency_code: str = ""
    improvement_requirement: str = ""
    first_seen_on: Optional[date] = None
    verification_method: str = ""


class DevelopmentIssuePatchIn(BaseModel):
    status: Optional[str] = None
    verification_method: Optional[str] = None
    improvement_requirement: Optional[str] = None


class DevelopmentMonthlyAssessmentIn(BaseModel):
    monthly_plan_id: int
    employee_self_review: str = ""
    mentor_review: str = ""
    completion_score: float = Field(default=0, ge=0, le=100)
    exercise_score: float = Field(default=0, ge=0, le=100)
    unfamiliar_case_score: float = Field(default=0, ge=0, le=100)
    project_performance_score: float = Field(default=0, ge=0, le=100)
    initiative_score: float = Field(default=0, ge=0, le=100)
    competency_changes: dict[str, Any] = Field(default_factory=dict)
    next_month_suggestion: str = ""
    status: str = "completed"


class DraftPlanIn(BaseModel):
    expected_project: str = ""
    template_code: str = ""


TrainingPlanStatus = Literal["draft", "not_started", "in_progress", "completed", "archived"]
TrainingTaskStatus = Literal["not_started", "in_progress", "submitted", "needs_revision", "completed", "blocked"]


class TrainingPlanIn(BaseModel):
    employee_id: int
    employee_code: str
    employee_name: str
    plan_type: str = "special_training"
    period: str
    title: str
    overall_goal: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: TrainingPlanStatus = "draft"
    mentor_id: Optional[int] = None


class TrainingWeekIn(BaseModel):
    training_plan_id: int
    week_no: int = Field(ge=1)
    title: str
    objective: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    expected_deliverable: str = ""
    sort_order: int = 0


class TrainingTaskIn(BaseModel):
    training_week_id: int
    task_code: str
    title: str
    description: str = ""
    task_type: Literal["learning", "quiz", "practice", "project", "assignment", "self_check", "review"] = "learning"
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    estimated_hours: Optional[float] = Field(default=None, ge=0)
    prerequisite_task_ids: list[int] = Field(default_factory=list)
    completion_criteria: str = ""
    submission_required: bool = False
    mentor_review_required: bool = False
    sort_order: int = 0
    status: TrainingTaskStatus = "not_started"


class LearningMaterialIn(BaseModel):
    task_id: int
    title: str
    material_type: Literal["itas_page", "external_link", "document", "video", "case", "reference"]
    course_scope: Literal["common", "personal"] = "personal"
    url: str = ""
    description: str = ""
    sort_order: int = 0


class TrainingSubmissionIn(BaseModel):
    task_id: int
    employee_id: int
    submission_type: str = "assignment"
    content: str = ""
    attachment: str = ""
    version: Optional[int] = Field(default=None, ge=1)
    status: str = "submitted"


class TrainingReviewIn(BaseModel):
    submission_id: int
    reviewer_id: int
    result: Literal["passed", "revision_required"]
    score: Optional[float] = Field(default=None, ge=0, le=100)
    comments: str = ""
    reviewed_at: Optional[datetime] = None


class TrainingBlockerIn(BaseModel):
    task_id: int
    employee_id: int
    problem: str
    confirmed_facts: str = ""
    materials_checked: str = ""
    initial_judgment: str = ""
    attempted_solutions: str = ""
    missing_information: str = ""
    mentor_question: str = ""
    status: str = "open"
    mentor_response: str = ""


class AssessmentDimensionIn(BaseModel):
    dimension_code: str
    dimension_name: str
    weight: float = Field(gt=0)
    score: Optional[float] = Field(default=None, ge=0, le=100)
    comments: str = ""
    sort_order: int = 0


class MonthlyAssessmentIn(BaseModel):
    training_plan_id: int
    employee_id: int
    period: str
    summary: str = ""
    total_score: Optional[float] = Field(default=None, ge=0, le=100)
    status: str = "draft"
    assessed_at: Optional[datetime] = None
    dimensions: list[AssessmentDimensionIn] = Field(default_factory=list)


class AutofillRuleActionPatchIn(BaseModel):
    action_status: Optional[str] = None
    action_note: Optional[str] = None
    source_verification_status: Optional[str] = None
    conflict_message: Optional[str] = None


class ReviewDecisionIn(BaseModel):
    reviewer_user_id: Optional[int] = None
    comment: str = ""


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
