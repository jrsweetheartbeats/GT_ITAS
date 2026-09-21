from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from html import escape as html_escape
import secrets
import shutil
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.config import BASE_DIR, TRAINING_SUBMISSIONS_ROOT
from ..core.security import current_user, ensure_feature_permission, is_admin
from ..models import (
    DevelopmentAssessmentDimension,
    DevelopmentBlocker,
    DevelopmentEmployee,
    DevelopmentCoursewareNote,
    DevelopmentLearningMaterial,
    DevelopmentLearningMaterialRead,
    DevelopmentTaskNote,
    DevelopmentMonthlyAssessment,
    DevelopmentSubmission,
    DevelopmentSubmissionReview,
    DevelopmentTrainingPlan,
    DevelopmentTrainingTask,
    DevelopmentTrainingWeek,
    User,
)
from ..services.courseware_notes import CHAPTER_BY_KEY, chapter_payload, group_notes_by_module
from ..services.training_plan_protocol import (
    ProtocolQuizQuestion,
    TrainingPlanDocument,
    training_plan_json,
    validate_training_plan_payload,
)
from ..services.training_signals import (
    LEARNER_SIGNAL_TYPES,
    build_review_evidence,
    record_learning_event,
    record_quiz_attempt,
)


router = APIRouter(prefix="/api/development/import", tags=["development-import"])
training_router = APIRouter(prefix="/api/development", tags=["development-training"])

# 执行人员只能访问自己的培养数据；经理及以上层级才可查看全员计划和导师工作台。
TRAINING_MANAGEMENT_ROLES = {"admin", "partner", "quality", "director", "senior_manager", "manager"}
PERSONAL_HANDBOOK_FILENAMES = {
    "ita_hyt": "黄译潼_第1个月特别培养计划_学员版.html",
    "ita_kc": "KC_第1个月特别培养计划_学员版.html",
    "ita_kmt": "康美婷_第1个月特别培养计划_学员版.html",
    "ita_kzj": "KZJ_第1个月特别培养计划_学员版.html",
    "ita_lsq": "LSQ_第1个月特别培养计划_学员版.html",
    "ita_wyx": "WYX_第1个月特别培养计划_学员版.html",
    "ita_cyx": "陈亦浠_第1个月特别培养计划_学员版.html",
    "ita_hhl": "HHL_第1个月特别培养计划.html",
    "ita_qmn": "QMN_第1个月特别培养计划_学员版.html",
    "ita_xhx": "XHX_第1个月特别培养计划_学员版.html",
}
PERSONAL_HANDBOOKS_ROOT = BASE_DIR.parent / "培养计划" / "第1个月培养计划"


def _can_manage_training(user: User) -> bool:
    return bool(user.role and user.role.code in TRAINING_MANAGEMENT_ROLES)


def _require_training_management(user: User) -> None:
    if not _can_manage_training(user):
        raise HTTPException(status_code=403, detail="只有经理及以上层级可以管理和查看全员培养计划")


def _error(path: str, message: str, code: str) -> dict[str, str]:
    return {"path": path, "message": message, "code": code}


def _user_for_code(db: Session, code: str) -> Optional[User]:
    normalized = str(code or "").strip().lower()
    if not normalized:
        return None
    user = db.execute(select(User).where(func.lower(User.username) == normalized)).scalar_one_or_none()
    if user is not None:
        return user
    profile = db.execute(select(DevelopmentEmployee).where(func.lower(DevelopmentEmployee.code) == normalized)).scalar_one_or_none()
    if profile is not None and profile.user_id:
        return db.get(User, profile.user_id)
    return None


def _resolve_people(db: Session, document: TrainingPlanDocument) -> tuple[Optional[User], Optional[User], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    employee = _user_for_code(db, document.employee.code)
    if employee is None:
        errors.append(_error("employee.code", f"找不到员工 {document.employee.code}。请先在 ITAS 用户/人员档案中建立并关联该员工。", "employee_not_found"))
    mentor = None
    if document.plan.mentor_code.strip():
        mentor = _user_for_code(db, document.plan.mentor_code)
        if mentor is None:
            errors.append(_error("plan.mentorCode", f"找不到导师 {document.plan.mentor_code}。请确认 mentorCode 使用 ITAS 用户账号或已关联人员简称。", "mentor_not_found"))
    return employee, mentor, errors


def _preview(document: TrainingPlanDocument, employee: Optional[User], mentor: Optional[User]) -> dict[str, Any]:
    tasks = [task for week in document.weeks for task in week.tasks]
    return {
        "employee": {
            "code": document.employee.code,
            "name": document.employee.name,
            "resolvedUserId": employee.id if employee else None,
            "resolvedDisplayName": employee.display_name if employee else None,
        },
        "mentor": {
            "code": document.plan.mentor_code,
            "resolvedUserId": mentor.id if mentor else None,
            "resolvedDisplayName": mentor.display_name if mentor else None,
        } if document.plan.mentor_code else None,
        "plan": {
            "title": document.plan.title,
            "type": document.plan.plan_type,
            "period": document.plan.period,
            "startDate": document.plan.start_date,
            "endDate": document.plan.end_date,
            "overallGoal": document.plan.overall_goal,
        },
        "counts": {
            "weeks": len(document.weeks),
            "tasks": len(tasks),
            "learningMaterials": sum(len(task.learning_materials) for task in tasks),
            "submissionRequiredTasks": sum(1 for task in tasks if task.submission.required),
            "mentorReviewTasks": sum(1 for task in tasks if task.mentor_review_required),
            "assessmentDimensions": len(document.assessment.dimensions),
        },
        "taskCodes": [task.task_code for task in tasks],
        "assessment": {
            "totalScore": document.assessment.total_score,
            "weightTotal": round(sum(item.weight for item in document.assessment.dimensions), 2),
            "thresholds": document.assessment.thresholds,
        },
    }


def _latest_submission(task: DevelopmentTrainingTask, employee_id: int) -> Optional[DevelopmentSubmission]:
    rows = [row for row in task.submissions if row.employee_id == employee_id]
    return max(rows, key=lambda row: (row.version, row.submitted_at or datetime.min), default=None)


def _training_plan_overview(plan: DevelopmentTrainingPlan) -> dict[str, Any]:
    today = datetime.now().date()
    weeks = sorted(plan.weeks, key=lambda row: (row.sort_order, row.week_no, row.id))
    all_tasks = [task for week in weeks for task in sorted(week.tasks, key=lambda row: (row.sort_order, row.id))]
    task_by_id = {task.id: task for task in all_tasks}
    task_payloads: list[dict[str, Any]] = []
    completed = pending_submission = pending_review = blocked = 0
    for task in all_tasks:
        latest = _latest_submission(task, plan.employee_id)
        has_submission = latest is not None
        review_pending = bool(task.mentor_review_required and latest and latest.status in {"submitted", "pending_review"})
        is_blocked = task.status == "blocked" or any(item.status in {"open", "pending", "in_progress"} for item in task.blockers)
        prerequisite_ids = _prerequisite_ids(task)
        unmet_prerequisites = [{"id": task_by_id[item_id].id, "taskCode": task_by_id[item_id].task_code, "title": task_by_id[item_id].title, "status": task_by_id[item_id].status} for item_id in prerequisite_ids if item_id in task_by_id and task_by_id[item_id].status != "completed"]
        if task.status == "completed":
            completed += 1
        if task.submission_required and not has_submission:
            pending_submission += 1
        if review_pending:
            pending_review += 1
        if is_blocked:
            blocked += 1
        task_payloads.append({
            "id": task.id,
            "taskCode": task.task_code,
            "title": task.title,
            "description": task.description,
            "instructions": task.instructions,
            "taskType": task.task_type,
            "startDate": task.start_date,
            "dueDate": task.due_date,
            "estimatedHours": task.estimated_hours,
            "completionCriteria": task.completion_criteria,
            "submissionRequired": task.submission_required,
            "submissionType": task.submission_type,
            "submissionTitle": task.submission_title,
            "submissionRequirements": task.submission_requirements,
            "mentorReviewRequired": task.mentor_review_required,
            "status": task.status,
            "isReviewPending": review_pending,
            "isBlocked": is_blocked,
            "locked": bool(unmet_prerequisites), "blockedByPrerequisite": bool(unmet_prerequisites), "prerequisites": unmet_prerequisites,
            "hasSubmission": has_submission,
            "latestSubmission": ({"id": latest.id, "version": latest.version, "status": latest.status, "submittedAt": latest.submitted_at} if latest else None),
            "materials": [{"id": item.id, "title": item.title, "type": item.material_type, "courseScope": item.course_scope, "url": item.url, "description": item.description} for item in sorted(task.materials, key=lambda row: (row.sort_order, row.id))],
            "weekNo": next((week.week_no for week in weeks if task in week.tasks), None),
        })
    current_week = next((week for week in weeks if week.start_date and week.end_date and week.start_date <= today <= week.end_date), None)
    return {
        "id": plan.id,
        "employee": {"id": plan.employee_id, "code": plan.employee_code, "name": plan.employee_name},
        "mentor": {"id": plan.mentor_id, "name": plan.mentor.display_name if plan.mentor else ""},
        "plan": {"title": plan.title, "type": plan.plan_type, "period": plan.period, "overallGoal": plan.overall_goal, "startDate": plan.start_date, "endDate": plan.end_date, "status": plan.status, "schemaVersion": plan.schema_version},
        "today": today,
        "currentWeekNo": current_week.week_no if current_week else None,
        "metrics": {"totalTasks": len(all_tasks), "completed": completed, "pendingSubmission": pending_submission, "pendingReview": pending_review, "blocked": blocked},
        "weeks": [{"id": week.id, "weekNo": week.week_no, "title": week.title, "objective": week.objective, "startDate": week.start_date, "endDate": week.end_date, "expectedDeliverable": week.expected_deliverable, "tasks": [item for item in task_payloads if item["weekNo"] == week.week_no]} for week in weeks],
        "tasks": task_payloads,
    }


@training_router.get("/training-plans")
def list_training_plans(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    ensure_feature_permission(db, user, "development", "view")
    query = select(DevelopmentTrainingPlan).order_by(DevelopmentTrainingPlan.start_date.desc(), DevelopmentTrainingPlan.id.desc())
    if not _can_manage_training(user):
        query = query.where(DevelopmentTrainingPlan.employee_id == user.id)
    rows = db.execute(query).scalars().all()
    return [{"id": row.id, "employeeCode": row.employee_code, "employeeName": row.employee_name, "title": row.title, "period": row.period, "startDate": row.start_date, "endDate": row.end_date, "status": row.status} for row in rows]


@training_router.get("/training-plans/{plan_id}/overview")
def training_plan_overview(plan_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    plan = db.get(DevelopmentTrainingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="培养计划不存在")
    if not _can_manage_training(user) and plan.employee_id != user.id:
        raise HTTPException(status_code=403, detail="只能查看自己的培养计划")
    return _training_plan_overview(plan)


def _learner_task_payload(
    task: DevelopmentTrainingTask,
    employee_id: int,
    today,
    prerequisites: Optional[list[dict[str, Any]]] = None,
    week_tasks: Optional[list[DevelopmentTrainingTask]] = None,
) -> dict[str, Any]:
    latest = _latest_submission(task, employee_id)
    latest_review = None
    if latest and latest.reviews:
        latest_review = max(latest.reviews, key=lambda row: (row.reviewed_at or datetime.min, row.id))
    prerequisites = prerequisites or []
    blocked_by_prerequisite = bool(prerequisites)
    is_overdue = bool(task.due_date and task.due_date < today and task.status != "completed")
    return {
        "id": task.id, "taskCode": task.task_code, "title": task.title, "description": task.description,
        "taskType": task.task_type, "estimatedHours": task.estimated_hours, "startDate": task.start_date,
        "dueDate": task.due_date, "status": task.status, "submissionRequired": task.submission_required,
        "mentorReviewRequired": task.mentor_review_required, "hasSubmission": latest is not None,
        "latestSubmission": ({"id": latest.id, "version": latest.version, "status": latest.status, "submittedAt": latest.submitted_at} if latest else None),
        "latestReview": ({"id": latest_review.id, "result": latest_review.result, "score": latest_review.score, "comments": latest_review.comments, "reviewedAt": latest_review.reviewed_at} if latest_review else None),
        "isOverdue": is_overdue, "blockedByPrerequisite": blocked_by_prerequisite, "locked": blocked_by_prerequisite,
        "prerequisites": prerequisites, "scheduledDate": task.start_date or task.due_date,
        "completionCriteria": task.completion_criteria, "submissionTitle": task.submission_title,
        "questionCount": len(_task_questions(task)),
        "relatedSubmissionTask": _related_submission_task(task, week_tasks or []),
    }


@training_router.get("/my-training")
def my_training(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    today = datetime.now().date()
    plan = db.execute(
        select(DevelopmentTrainingPlan)
        .where(DevelopmentTrainingPlan.employee_id == user.id, DevelopmentTrainingPlan.status != "archived")
        .order_by(DevelopmentTrainingPlan.start_date.desc(), DevelopmentTrainingPlan.id.desc())
    ).scalars().first()
    if plan is None:
        return {"today": today, "employee": {"id": user.id, "name": user.display_name, "code": user.username}, "plan": None, "week": None, "tasks": [], "submissions": {"pending": [], "passed": 0, "revisionRequired": 0}, "blockers": [], "metrics": {"completed": 0, "total": 0, "completionRate": 0}}
    weeks = sorted(plan.weeks, key=lambda row: (row.sort_order, row.week_no, row.id))
    current_week = next((week for week in weeks if week.start_date and week.end_date and week.start_date <= today <= week.end_date), None)
    if current_week is None:
        current_week = next((week for week in weeks if week.end_date and week.end_date >= today), weeks[-1] if weeks else None)
    all_tasks = [task for week in weeks for task in week.tasks]
    current_tasks = [task for task in (current_week.tasks if current_week else [])]
    task_by_id = {task.id: task for task in all_tasks}
    batch_payloads: list[dict[str, Any]] = []
    for week in weeks:
        week_tasks = sorted(week.tasks, key=lambda task: (task.sort_order, task.id))
        tasks = [
            _learner_task_payload(task, user.id, today, _prerequisite_payload(db, task), week_tasks)
            for task in week_tasks
        ]
        batch_payloads.append({
            "id": week.id,
            "batchNo": week.week_no,
            "title": week.title,
            "objective": week.objective,
            "startDate": week.start_date,
            "endDate": week.end_date,
            "expectedDeliverable": week.expected_deliverable,
            "progress": {
                "completed": sum(1 for task in week_tasks if task.status == "completed"),
                "total": len(week_tasks),
            },
            "tasks": tasks,
        })
    payloads = [
        _learner_task_payload(task, user.id, today, _prerequisite_payload(db, task), current_tasks)
        for task in current_tasks
    ]
    for item, task in zip(payloads, current_tasks):
        item["blockedByPrerequisite"] = bool(item.get("prerequisites"))
        item["locked"] = item["blockedByPrerequisite"]
    def priority(item: dict[str, Any]) -> tuple[int, str]:
        if item["isOverdue"]: return (0, str(item["dueDate"] or ""))
        if item["dueDate"] == today: return (1, str(item["dueDate"] or ""))
        if item["submissionRequired"] and not item["hasSubmission"] and not item["blockedByPrerequisite"]:
            return (2, str(item["dueDate"] or ""))
        if item["status"] == "in_progress": return (2, str(item["dueDate"] or ""))
        if not item["blockedByPrerequisite"] and item["status"] == "not_started": return (3, str(item["dueDate"] or ""))
        return (4, str(item["dueDate"] or ""))
    payloads.sort(key=priority)
    pending_submissions = [item for item in payloads if item["submissionRequired"] and not item["hasSubmission"]]
    required_submissions = [item for item in payloads if item["submissionRequired"]]
    agenda_tasks = sorted(payloads, key=lambda item: (str(item.get("scheduledDate") or item.get("dueDate") or "9999-12-31"), priority(item)))
    daily_dates = []
    for item in agenda_tasks:
        date = item.get("scheduledDate") or item.get("dueDate")
        if date and date not in daily_dates:
            daily_dates.append(date)
    daily_agenda = [{"date": date, "tasks": [item for item in agenda_tasks if (item.get("scheduledDate") or item.get("dueDate")) == date]} for date in daily_dates]
    passed = revision_required = 0
    for task in all_tasks:
        latest = _latest_submission(task, user.id)
        review = max(latest.reviews, key=lambda row: (row.reviewed_at or datetime.min, row.id)) if latest and latest.reviews else None
        if review and review.result == "passed": passed += 1
        if review and review.result == "revision_required": revision_required += 1
    blockers = db.execute(select(DevelopmentBlocker).where(DevelopmentBlocker.employee_id == user.id, DevelopmentBlocker.status.in_(["open", "pending", "in_progress"])).order_by(DevelopmentBlocker.created_at.desc())).scalars().all()
    completed = sum(1 for task in all_tasks if task.status == "completed")
    return {
        "today": today,
        "employee": {"id": user.id, "name": user.display_name or plan.employee_name, "code": plan.employee_code},
        "plan": {"id": plan.id, "title": plan.title, "period": plan.period, "overallGoal": plan.overall_goal, "startDate": plan.start_date, "endDate": plan.end_date, "status": plan.status},
        "week": ({"id": current_week.id, "weekNo": current_week.week_no, "title": current_week.title, "objective": current_week.objective, "startDate": current_week.start_date, "endDate": current_week.end_date, "progress": {"completed": sum(1 for task in current_tasks if task.status == "completed"), "total": len(current_tasks)}} if current_week else None),
        "batches": batch_payloads,
        "tasks": payloads,
        "dailyTasks": agenda_tasks,
        "dailyAgenda": daily_agenda,
        "submissions": {"pending": pending_submissions, "required": required_submissions, "passed": passed, "revisionRequired": revision_required},
        "blockers": [{"id": item.id, "taskId": item.task_id, "problem": item.problem, "confirmedFacts": item.confirmed_facts, "materialsChecked": item.materials_checked, "initialJudgment": item.initial_judgment, "attemptedSolutions": item.attempted_solutions, "missingInformation": item.missing_information, "mentorQuestion": item.mentor_question, "blockerType": item.blocker_type, "selfAnalysisComplete": item.self_analysis_complete, "status": item.status, "mentorResponse": item.mentor_response, "resolutionAction": item.resolution_action, "createdAt": item.created_at, "resolvedAt": item.resolved_at, "durationDays": max(0, (item.resolved_at or datetime.now()).date().toordinal() - item.created_at.date().toordinal()) if item.created_at else None} for item in blockers],
        "metrics": {"completed": completed, "total": len(all_tasks), "completionRate": round(completed / len(all_tasks) * 100) if all_tasks else 0},
    }


@training_router.get("/my-training/handbook")
def download_my_training_handbook(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> FileResponse:
    """Serve only the signed-in learner's personal handbook."""
    ensure_feature_permission(db, user, "development", "view")
    filename = PERSONAL_HANDBOOK_FILENAMES.get((user.username or "").strip().lower())
    if filename is None:
        raise HTTPException(status_code=404, detail="当前账号尚未配置个人培养手册")
    path = (PERSONAL_HANDBOOKS_ROOT / filename).resolve(strict=False)
    try:
        path.relative_to(PERSONAL_HANDBOOKS_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="个人培养手册不可用") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="个人培养手册文件不存在")
    return FileResponse(path, media_type="text/html", filename=filename)


@training_router.post("/my-training/blockers")
def create_my_training_blocker(payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task_id = payload.get("taskId")
    fields = ["problem", "confirmedFacts", "materialsChecked", "initialJudgment", "attemptedSolutions", "missingInformation", "mentorQuestion"]
    values = {field: str(payload.get(field) or "").strip() for field in fields}
    if not task_id or any(not values[field] for field in fields):
        raise HTTPException(status_code=422, detail={"message": "提交卡点前必须完成全部结构化分析。", "requiredFields": fields})
    task = db.get(DevelopmentTrainingTask, int(task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="培养任务不存在")
    plan = db.get(DevelopmentTrainingWeek, task.training_week_id).training_plan_id
    owner_plan = db.get(DevelopmentTrainingPlan, plan)
    if owner_plan is None or owner_plan.employee_id != user.id:
        raise HTTPException(status_code=403, detail="只能为自己的培养任务提交卡点")
    blocker = DevelopmentBlocker(task_id=task.id, employee_id=user.id, problem=values["problem"], confirmed_facts=values["confirmedFacts"], materials_checked=values["materialsChecked"], initial_judgment=values["initialJudgment"], attempted_solutions=values["attemptedSolutions"], missing_information=values["missingInformation"], mentor_question=values["mentorQuestion"], blocker_type=str(payload.get("blockerType") or "general"), self_analysis_complete=True, status="open")
    db.add(blocker)
    task.status = "blocked"
    record_learning_event(
        db,
        employee_id=user.id,
        event_type="blocker_submitted",
        task=task,
        skill_tag="independence",
        source="learner",
        payload={"blockerType": blocker.blocker_type, "selfAnalysisComplete": True},
    )
    db.commit()
    db.refresh(blocker)
    return {"id": blocker.id, "status": blocker.status, "taskStatus": task.status, "message": "卡点已提交，任务已标记为 Blocked"}


def _blocker_payload(row: DevelopmentBlocker) -> dict[str, Any]:
    created = row.created_at
    resolved = row.resolved_at
    return {"id": row.id, "taskId": row.task_id, "employeeId": row.employee_id, "employeeName": row.employee.display_name if row.employee else "", "problem": row.problem, "confirmedFacts": row.confirmed_facts, "materialsChecked": row.materials_checked, "initialJudgment": row.initial_judgment, "attemptedSolutions": row.attempted_solutions, "missingInformation": row.missing_information, "mentorQuestion": row.mentor_question, "blockerType": row.blocker_type, "selfAnalysisComplete": row.self_analysis_complete, "status": row.status, "mentorResponse": row.mentor_response, "resolutionAction": row.resolution_action, "createdAt": created, "resolvedAt": resolved, "durationDays": max(0, (resolved or datetime.now()).date().toordinal() - created.date().toordinal()) if created else None}


@training_router.get("/blockers/pending")
def pending_training_blockers(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    ensure_feature_permission(db, user, "development", "view")
    _require_training_management(user)
    rows = db.execute(select(DevelopmentBlocker).where(DevelopmentBlocker.status.in_(["open", "self_processing"])).order_by(DevelopmentBlocker.created_at.asc(), DevelopmentBlocker.id.asc())).scalars().all()
    return [_blocker_payload(row) for row in rows]


@training_router.get("/blockers/{blocker_id}")
def training_blocker_detail(blocker_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    row = db.get(DevelopmentBlocker, blocker_id)
    if row is None:
        raise HTTPException(status_code=404, detail="卡点不存在")
    if row.employee_id != user.id:
        _require_training_management(user)
    return _blocker_payload(row)


@training_router.patch("/blockers/{blocker_id}/respond")
def respond_training_blocker(blocker_id: int, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "edit")
    _require_training_management(user)
    row = db.get(DevelopmentBlocker, blocker_id)
    if row is None:
        raise HTTPException(status_code=404, detail="卡点不存在")
    action = str(payload.get("action") or "").strip()
    response = str(payload.get("mentorResponse") or "").strip()
    if action not in {"continue_self_processing", "resolved"}:
        raise HTTPException(status_code=422, detail="action 必须为 continue_self_processing 或 resolved")
    if not response:
        raise HTTPException(status_code=422, detail="导师回复不能为空")
    row.mentor_response = response
    row.resolution_action = action
    task = db.get(DevelopmentTrainingTask, row.task_id)
    if action == "continue_self_processing":
        row.status = "self_processing"
        if task: task.status = "in_progress"
    else:
        row.status = "resolved"
        row.resolved_by_user_id = user.id
        row.resolved_at = datetime.utcnow()
        if task: task.status = "in_progress"
    record_learning_event(
        db,
        employee_id=row.employee_id,
        event_type="blocker_resolved" if action == "resolved" else "blocker_continued",
        task=task,
        skill_tag="independence",
        source="mentor",
        payload={"action": action, "blockerId": row.id},
    )
    db.commit()
    db.refresh(row)
    return {"message": "卡点处理结果已保存", "blocker": _blocker_payload(row), "taskStatus": task.status if task else None}


def _mentor_can_access_plan(plan: DevelopmentTrainingPlan, user: User) -> bool:
    return _can_manage_training(user)


_LEGACY_TRAINING_PREFIX = "/static/uploads/training_submissions/"
_PRIVATE_TRAINING_PREFIX = "training-submission:"


def _private_submission_name(reference: str) -> str | None:
    if not reference.startswith(_PRIVATE_TRAINING_PREFIX):
        return None
    name = Path(reference.removeprefix(_PRIVATE_TRAINING_PREFIX)).name
    return name if name and name != "." else None


def _submission_attachment_url(row: DevelopmentSubmission) -> str:
    return f"/api/development/submissions/{row.id}/attachment" if _private_submission_name(row.attachment or "") else row.attachment


def migrate_training_submission_attachments(db: Session) -> None:
    """Move legacy public uploads once and replace their public URLs with private references."""
    legacy_root = BASE_DIR / "static" / "uploads" / "training_submissions"
    rows = db.execute(select(DevelopmentSubmission).where(DevelopmentSubmission.attachment.like(f"{_LEGACY_TRAINING_PREFIX}%"))).scalars().all()
    if not rows and not legacy_root.is_dir():
        return
    TRAINING_SUBMISSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    for row in rows:
        name = Path(row.attachment.removeprefix(_LEGACY_TRAINING_PREFIX)).name
        if not name or name == ".":
            continue
        source = legacy_root / name
        target = TRAINING_SUBMISSIONS_ROOT / name
        if source.is_file():
            if target.exists():
                source.unlink()
            else:
                shutil.move(str(source), str(target))
        row.attachment = f"{_PRIVATE_TRAINING_PREFIX}{name}"
    # Any orphaned legacy upload is still public while left below /static.
    # Preserve it in the private store too, rather than deleting user data.
    if legacy_root.is_dir():
        for source in legacy_root.rglob("*"):
            if not source.is_file():
                continue
            target = TRAINING_SUBMISSIONS_ROOT / source.name
            if target.exists():
                source.unlink()
            else:
                shutil.move(str(source), str(target))
    db.commit()


def _assessment_payload(assessment: Optional[DevelopmentMonthlyAssessment]) -> Optional[dict[str, Any]]:
    if assessment is None:
        return None
    return {"id": assessment.id, "period": assessment.period, "status": assessment.status, "totalScore": assessment.total_score, "summary": json.loads(assessment.summary or "{}") if assessment.summary.startswith("{") else assessment.summary, "thresholds": json.loads(assessment.thresholds_json or "[]"), "dimensions": [{"id": item.id, "code": item.dimension_code, "name": item.dimension_name, "weight": item.weight, "score": item.score, "description": item.description, "comments": item.comments} for item in sorted(assessment.dimensions, key=lambda item: (item.sort_order, item.id))]}


@training_router.get("/mentor-workbench")
def mentor_workbench(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    if not _can_manage_training(user):
        raise HTTPException(status_code=403, detail="只有经理及以上层级可以进入 Mentor 工作台")
    plans = db.execute(select(DevelopmentTrainingPlan).where(DevelopmentTrainingPlan.status != "archived").order_by(DevelopmentTrainingPlan.employee_name, DevelopmentTrainingPlan.id)).scalars().all()
    plans = [plan for plan in plans if _mentor_can_access_plan(plan, user)]
    today = datetime.now().date()
    students: list[dict[str, Any]] = []
    action_items: list[dict[str, Any]] = []
    for plan in plans:
        tasks = sorted((task for week in plan.weeks for task in week.tasks), key=lambda item: (item.due_date or today, item.sort_order, item.id))
        completed = sum(1 for task in tasks if task.status == "completed")
        overdue = [task for task in tasks if task.due_date and task.due_date < today and task.status not in {"completed", "blocked"}]
        pending_reviews = []
        task_payloads = []
        last_activity = None
        for task in tasks:
            latest = _latest_submission(task, plan.employee_id)
            if latest and latest.submitted_at and (last_activity is None or latest.submitted_at > last_activity):
                last_activity = latest.submitted_at
            is_pending_review = bool(task.mentor_review_required and latest and latest.status in {"submitted", "pending_review"})
            if is_pending_review:
                pending_reviews.append({"type": "review", "id": latest.id, "planId": plan.id, "taskId": task.id, "employeeName": plan.employee_name, "taskCode": task.task_code, "title": task.title, "dueDate": task.due_date, "createdAt": latest.submitted_at})
            task_payloads.append({
                "id": task.id, "taskCode": task.task_code, "title": task.title, "taskType": task.task_type,
                "status": task.status, "dueDate": task.due_date, "submissionRequired": task.submission_required,
                "mentorReviewRequired": task.mentor_review_required, "hasSubmission": latest is not None,
                "latestSubmissionId": latest.id if latest else None, "isReviewPending": is_pending_review,
                "submittedAt": latest.submitted_at if latest else None,
            })
        blockers = db.execute(select(DevelopmentBlocker).where(DevelopmentBlocker.employee_id == plan.employee_id, DevelopmentBlocker.task_id.in_([task.id for task in tasks]) if tasks else False, DevelopmentBlocker.status.in_(["open", "self_processing"]))).scalars().all()
        current_week = next((week for week in sorted(plan.weeks, key=lambda item: item.week_no) if week.start_date and week.end_date and week.start_date <= today <= week.end_date), None)
        assessment = next((item for item in plan.assessments if item.period == plan.period), None)
        active_tasks = sum(1 for task in tasks if task.status in {"in_progress", "submitted", "needs_revision"})
        activity_score = len(pending_reviews) * 100 + len(blockers) * 60 + len(overdue) * 20 + active_tasks * 5
        students.append({
            "planId": plan.id, "employeeId": plan.employee_id, "employeeCode": plan.employee_code, "employeeName": plan.employee_name,
            "completionRate": round(completed / len(tasks) * 100) if tasks else 0, "overdueTasks": len(overdue),
            "pendingReview": len(pending_reviews), "blocked": len(blockers), "activeTasks": active_tasks,
            "activityScore": activity_score, "lastActivityAt": last_activity, "tasks": task_payloads,
            "currentWeekNo": current_week.week_no if current_week else None, "period": plan.period,
            "assessmentStatus": assessment.status if assessment else "draft",
        })
        action_items.extend(pending_reviews)
        action_items.extend({"type": "blocker", "id": item.id, "planId": plan.id, "taskId": item.task_id, "employeeName": plan.employee_name, "title": item.problem, "createdAt": item.created_at} for item in blockers)
        action_items.extend({"type": "overdue", "id": task.id, "planId": plan.id, "taskId": task.id, "employeeName": plan.employee_name, "taskCode": task.task_code, "title": task.title, "dueDate": task.due_date} for task in overdue if task.submission_required or task.mentor_review_required)
        if assessment is not None and assessment.status in {"draft", "pending"} and plan.end_date and plan.end_date <= today:
            action_items.append({"type": "assessment", "id": assessment.id, "planId": plan.id, "employeeName": plan.employee_name, "period": plan.period, "title": f"{plan.period} 月度评价待评分"})
    students.sort(key=lambda item: (-item["activityScore"], item["lastActivityAt"] or datetime.min, item["employeeName"]), reverse=False)
    priority = {"review": 0, "blocker": 1, "overdue": 2, "assessment": 3}
    action_items.sort(key=lambda item: (priority.get(item["type"], 9), item.get("createdAt") or datetime.min, item.get("dueDate") or today))
    return {"students": students, "actionItems": action_items}


@training_router.get("/mentor/submissions/{submission_id}")
def mentor_submission_detail(submission_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    submission = db.get(DevelopmentSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="作业提交不存在")
    task = db.get(DevelopmentTrainingTask, submission.task_id)
    week = db.get(DevelopmentTrainingWeek, task.training_week_id) if task else None
    plan = db.get(DevelopmentTrainingPlan, week.training_plan_id) if week else None
    if plan is None or not _mentor_can_access_plan(plan, user):
        raise HTTPException(status_code=403, detail="无权查看该学员提交")
    return {"task": {"id": task.id, "taskCode": task.task_code, "title": task.title, "description": task.description, "purpose": task.purpose, "instructions": task.instructions, "completionCriteria": task.completion_criteria, "submissionRequirements": task.submission_requirements}, "employee": {"id": plan.employee_id, "code": plan.employee_code, "name": plan.employee_name}, "submissions": [_submission_payload(item) for item in sorted(task.submissions, key=lambda item: item.version)]}


def _assessment_for_plan(db: Session, plan: DevelopmentTrainingPlan) -> DevelopmentMonthlyAssessment:
    assessment = next((item for item in plan.assessments if item.period == plan.period), None)
    if assessment is None:
        raise HTTPException(status_code=404, detail="该培养计划尚未配置月度评价")
    return assessment


def _assessment_summary(db: Session, plan: DevelopmentTrainingPlan, assessment: DevelopmentMonthlyAssessment, mentor_evaluation: str, next_stage_suggestion: str) -> dict[str, Any]:
    tasks = [task for week in plan.weeks for task in week.tasks]
    completed = [{"taskCode": task.task_code, "title": task.title} for task in tasks if task.status == "completed"]
    incomplete = [{"taskCode": task.task_code, "title": task.title, "status": task.status} for task in tasks if task.status != "completed"]
    reviews = []
    for task in tasks:
        for submission in task.submissions:
            for review in submission.reviews:
                reviews.append({"taskCode": task.task_code, "version": submission.version, "result": review.result, "score": review.score, "comments": review.comments, "reviewedAt": review.reviewed_at})
    blockers = db.execute(select(DevelopmentBlocker).where(DevelopmentBlocker.employee_id == plan.employee_id, DevelopmentBlocker.task_id.in_([task.id for task in tasks]) if tasks else False)).scalars().all()
    return {
        "totalScore": assessment.total_score,
        "dimensions": [{"code": item.dimension_code, "name": item.dimension_name, "weight": item.weight, "score": item.score, "comments": item.comments} for item in sorted(assessment.dimensions, key=lambda item: item.sort_order)],
        "completedTasks": completed,
        "incompleteTasks": incomplete,
        "reviewHistory": reviews,
        "blockers": [_blocker_payload(item) for item in blockers],
        "mentorEvaluation": mentor_evaluation,
        "nextStageSuggestion": next_stage_suggestion,
        "objectiveEvidence": build_review_evidence(db, plan),
    }


def _weighted_assessment_total(dimensions: list[Any]) -> float:
    return round(sum((item.score or 0) * float(item.weight) / 100 for item in dimensions), 2)


@training_router.get("/mentor/plans/{plan_id}/assessment")
def mentor_assessment_detail(plan_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    plan = db.get(DevelopmentTrainingPlan, plan_id)
    if plan is None or not _mentor_can_access_plan(plan, user):
        raise HTTPException(status_code=404, detail="培养计划不存在或无权访问")
    assessment = _assessment_for_plan(db, plan)
    evidence = build_review_evidence(db, plan)
    db.commit()
    return {
        "plan": {"id": plan.id, "employeeCode": plan.employee_code, "employeeName": plan.employee_name, "period": plan.period, "title": plan.title},
        "assessment": _assessment_payload(assessment),
        "objectiveEvidence": evidence,
    }


@training_router.get("/mentor/plans/{plan_id}/review-evidence")
def mentor_review_evidence(plan_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    plan = db.get(DevelopmentTrainingPlan, plan_id)
    if plan is None or not _mentor_can_access_plan(plan, user):
        raise HTTPException(status_code=404, detail="培养计划不存在或无权访问")
    evidence = build_review_evidence(db, plan)
    db.commit()
    return evidence


@training_router.put("/mentor/plans/{plan_id}/assessment")
def save_mentor_assessment(plan_id: int, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "edit")
    plan = db.get(DevelopmentTrainingPlan, plan_id)
    if plan is None or not _mentor_can_access_plan(plan, user):
        raise HTTPException(status_code=404, detail="培养计划不存在或无权访问")
    assessment = _assessment_for_plan(db, plan)
    scores = payload.get("dimensions") or {}
    for dimension in assessment.dimensions:
        raw = scores.get(dimension.dimension_code)
        if raw is None:
            raise HTTPException(status_code=422, detail=f"缺少评分维度：{dimension.dimension_name}")
        score = float(raw)
        if score < 0 or score > 100:
            raise HTTPException(status_code=422, detail=f"评分必须在0到100之间：{dimension.dimension_name}")
        dimension.score = score
        dimension.comments = str((payload.get("dimensionComments") or {}).get(dimension.dimension_code) or "")
    weighted_total = _weighted_assessment_total(assessment.dimensions)
    suggestion = ""
    for threshold in sorted(json.loads(assessment.thresholds_json or "[]"), key=lambda item: item.get("min", 0)):
        if threshold.get("min", 0) <= weighted_total <= threshold.get("max", 100):
            suggestion = threshold.get("nextAction", "")
            break
    mentor_evaluation = str(payload.get("mentorEvaluation") or "").strip()
    next_stage_suggestion = str(payload.get("nextStageSuggestion") or suggestion).strip()
    summary = _assessment_summary(db, plan, assessment, mentor_evaluation, next_stage_suggestion)
    assessment.total_score = weighted_total
    assessment.summary = json.dumps(summary, ensure_ascii=False, default=str)
    assessment.status = "completed"
    assessment.assessed_at = datetime.utcnow()
    db.commit()
    db.refresh(assessment)
    return {"message": "月度评价已保存", "assessment": _assessment_payload(assessment), "summary": summary, "thresholdSuggestion": suggestion}


@training_router.get("/mentor/plans/{plan_id}/assessment/export")
def export_mentor_assessment(plan_id: int, format: str = "json", db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    plan = db.get(DevelopmentTrainingPlan, plan_id)
    if plan is None or not _mentor_can_access_plan(plan, user):
        raise HTTPException(status_code=404, detail="培养计划不存在或无权访问")
    assessment = _assessment_for_plan(db, plan)
    summary = json.loads(assessment.summary or "{}")
    if format.lower() == "markdown":
        evidence = summary.get("objectiveEvidence") or {}
        signals = evidence.get("objectiveSignals") or {}
        quiz = signals.get("quiz") or {}
        lines = [f"# {plan.employee_name} {plan.period} 月度培养结果", f"- 总分：{assessment.total_score}", f"- Mentor评价：{summary.get('mentorEvaluation', '')}", f"- 下阶段建议：{summary.get('nextStageSuggestion', '')}", "", "## 能力维度"]
        lines.extend(f"- {item.get('name')}：{item.get('score')} / 100（权重 {item.get('weight')}%）" for item in summary.get("dimensions", []))
        lines.extend(["", "## 已完成任务"] + [f"- {item.get('taskCode')} {item.get('title')}" for item in summary.get("completedTasks", [])])
        lines.extend(["", "## 客观学习信号", f"- 完成率：{(signals.get('completion') or {}).get('completionRate')}", f"- 选择题首过率：{quiz.get('firstPassRate')}", f"- 仍未过关题数：{quiz.get('stillWrongCount')}", f"- 卡点数：{(signals.get('blockers') or {}).get('count')}"])
        lines.extend(["", "## 可引用能力对照"] + [f"- {item.get('label')}：{item.get('objectiveNote')}" for item in evidence.get("reviewHints", [])])
        return {"format": "markdown", "content": "\n".join(lines), "summary": summary}
    return {"format": "json", "content": summary, "summary": summary}


def _owned_training_task(db: Session, task_id: int, employee_id: int) -> DevelopmentTrainingTask:
    task = db.get(DevelopmentTrainingTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="培养任务不存在")
    week = db.get(DevelopmentTrainingWeek, task.training_week_id)
    plan = db.get(DevelopmentTrainingPlan, week.training_plan_id) if week else None
    if plan is None or plan.employee_id != employee_id:
        raise HTTPException(status_code=403, detail="无权访问该培养任务")
    return task


def _prerequisite_ids(task: DevelopmentTrainingTask) -> list[int]:
    try:
        values = json.loads(task.prerequisite_task_ids or "[]")
    except (TypeError, ValueError):
        values = []
    return [int(value) for value in values if str(value).isdigit()]


def _unmet_prerequisites(db: Session, task: DevelopmentTrainingTask) -> list[DevelopmentTrainingTask]:
    ids = _prerequisite_ids(task)
    if not ids:
        return []
    rows = db.execute(select(DevelopmentTrainingTask).where(DevelopmentTrainingTask.id.in_(ids))).scalars().all()
    by_id = {row.id: row for row in rows}
    return [by_id[item_id] for item_id in ids if item_id in by_id and by_id[item_id].status != "completed"]


def _prerequisite_payload(db: Session, task: DevelopmentTrainingTask) -> list[dict[str, Any]]:
    return [{"id": item.id, "taskCode": item.task_code, "title": item.title, "status": item.status} for item in _unmet_prerequisites(db, task)]


def _ensure_task_unlocked(db: Session, task: DevelopmentTrainingTask) -> None:
    unmet = _prerequisite_payload(db, task)
    if unmet:
        raise HTTPException(status_code=409, detail={"message": "前置任务尚未完成，当前任务暂未解锁。", "locked": True, "prerequisites": unmet})


def _submission_payload(row: DevelopmentSubmission) -> dict[str, Any]:
    reviews = sorted(row.reviews, key=lambda item: (item.reviewed_at or datetime.min, item.id))
    return {
        "id": row.id, "version": row.version, "submissionType": row.submission_type,
        "content": row.content, "attachment": _submission_attachment_url(row), "selfCheckAnswers": json.loads(row.self_check_answers or "{}"),
        "submittedAt": row.submitted_at, "status": row.status,
        "reviews": [{"id": item.id, "reviewerId": item.reviewer_id, "result": item.result, "score": item.score, "comments": item.comments, "reviewedAt": item.reviewed_at} for item in reviews],
    }


def _task_questions(task: DevelopmentTrainingTask) -> list[Any]:
    try:
        value = json.loads(task.self_check_questions or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _related_submission_task(
    task: DevelopmentTrainingTask, week_tasks: list[DevelopmentTrainingTask]
) -> Optional[dict[str, Any]]:
    """Point a reading-only task at the actionable assignment in its week.

    Existing imported plans often split a week into a learning task and a
    separate formal assignment.  The former deliberately has no quiz or
    submission form, so exposing the latter prevents learners from reaching a
    dead end after opening the learning task.
    """
    if task.submission_required:
        return None
    candidates = sorted(week_tasks, key=lambda item: (item.sort_order, item.id))
    linked = next((item for item in candidates if item.id != task.id and item.submission_required), None)
    if linked is None:
        return None
    return {
        "id": linked.id,
        "title": linked.submission_title or linked.title,
        "questionCount": len(_task_questions(linked)),
        "submissionRequired": True,
    }


def _public_task_questions(task: DevelopmentTrainingTask) -> list[Any]:
    questions = _task_questions(task)
    return [
        ({key: value for key, value in question.items() if key != "answer"} if isinstance(question, dict) else question)
        for question in questions
    ]


def _validate_task_questions(questions: list[Any], answers: Any) -> tuple[list[Any], list[Any]]:
    answers = answers if isinstance(answers, dict) else {}
    missing: list[Any] = []
    incorrect: list[Any] = []
    for index, question in enumerate(questions):
        value = answers.get(str(index), answers.get(index, answers.get(question) if isinstance(question, str) else None))
        if isinstance(question, str):
            if value is not True:
                missing.append(question)
            continue
        if not isinstance(question, dict) or question.get("type") not in {"choice", "fill_blank"}:
            continue
        expected = question.get("answer")
        expected_values = expected if isinstance(expected, list) else [expected]
        actual_values = value if isinstance(value, list) else [value]
        normalize = lambda item: str(item or "").strip().casefold()
        expected_normalized = sorted(normalize(item) for item in expected_values)
        actual_normalized = sorted(normalize(item) for item in actual_values if item is not None and str(item).strip())
        if not actual_normalized:
            missing.append(question.get("prompt", f"第{index + 1}题"))
        elif actual_normalized != expected_normalized:
            incorrect.append(question.get("prompt", f"第{index + 1}题"))
    return missing, incorrect


def _question_feedback(questions: list[Any], answers: Any) -> list[dict[str, Any]]:
    answers = answers if isinstance(answers, dict) else {}
    feedback: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        prompt = str(question.get("prompt") or f"第{index + 1}题")
        submitted = answers.get(str(index), answers.get(index))
        expected = question.get("answer")
        expected_values = expected if isinstance(expected, list) else [expected]
        submitted_values = submitted if isinstance(submitted, list) else [submitted]
        normalize = lambda item: str(item or "").strip().casefold()
        expected_normalized = sorted(normalize(item) for item in expected_values)
        submitted_normalized = sorted(normalize(item) for item in submitted_values if item is not None and str(item).strip())
        status = "missing" if not submitted_normalized else ("correct" if submitted_normalized == expected_normalized else "incorrect")
        feedback.append({
            "index": index,
            "prompt": prompt,
            "status": status,
            "submittedAnswer": submitted,
            "correctAnswer": expected,
            "explanation": question.get("explanation") or "请回到关联课程复核该知识点。",
        })
    return feedback


def _question_error(questions: list[Any], answers: Any, missing: list[Any], incorrect: list[Any]) -> dict[str, Any]:
    errors = []
    if missing:
        errors.append("请完成全部每日任务题目。")
    if incorrect:
        errors.append("选择题存在错误，请根据逐题解析复核后重新提交。")
    return {
        "message": " ".join(errors),
        "missingQuestions": missing,
        "incorrectQuestions": incorrect,
        "questionFeedback": _question_feedback(questions, answers),
    }


def _courseware_reason(task: DevelopmentTrainingTask) -> tuple[str, str, str]:
    text = f"{task.title} {task.description} {task.purpose}".lower()
    if any(key in text for key in ("itac", "ipe", "interface", "接口")):
        return ("自动控制、接口与 IPE", "自动控制、接口和系统生成信息的价值，在于持续、完整且准确地影响业务处理或审计判断。", "避免接口漏传、重复传输、参数变更或报表筛选错误在没有被发现的情况下进入财务报告或审计结论。")
    if any(key in text for key in ("itgc", "权限", "账号", "变更", "备份", "日志")):
        return ("IT 一般控制", "ITGC 通过授权、变更、运行和恢复控制，保证系统处理环境在整个期间内保持可靠。", "避免未授权访问、未经测试的变更、故障恢复失败或关键日志缺失削弱业务数据和自动控制的可信度。")
    if any(key in text for key in ("数据", "caats", "sql", "交叉验证")):
        return ("审计数据分析", "数据分析只有在总体、字段口径、关联规则和异常追溯路径明确时，才能形成审计证据。", "避免因为错误关联、总体遗漏或口径不一致而把技术输出误当作审计结论。")
    if any(key in text for key in ("业务", "财务", "收入", "科目", "认定")):
        return ("业务与财务链路", "业务事件经系统处理后才形成会计记录；理解这条链路才能判断异常影响的科目和认定。", "避免只核对金额或系统截图，却没有识别收入、存货、资金等业务数据遗漏或错误入账的风险。")
    if any(key in text for key in ("scope", "范围", "系统")):
        return ("审计范围", "审计范围不是系统清单，而是识别哪些系统会处理、传输或影响重大流程、财务数据和关键认定。", "避免只因系统名称或历史模板而遗漏关键系统，或把与财务报告无关的系统无效纳入范围。")
    return ("审计判断与证据", "每一项审计训练都应从风险、判断依据、执行程序和结论边界四个层面建立完整链路。", "避免只完成表面动作而没有说明证据如何支持结论，或没有识别同类问题在其他底稿中的影响。")


def _courseware_chapter(task: DevelopmentTrainingTask) -> dict[str, Any]:
    """Provide the explanatory core for the task's textbook-style lesson."""
    text = f"{task.title} {task.description} {task.purpose}".lower()
    if any(key in text for key in ("itac", "ipe", "interface", "接口", "自动")):
        return {
            "definition": "ITAC 是嵌入应用系统处理逻辑中的自动控制。它并不等同于“系统会计算”或“页面有提示”，而是要求系统在满足预设条件时，能够自动预防、发现或纠正会影响业务处理和财务报告的错误。IPE 是由系统生成并被控制或审计程序使用的信息，例如例外报表、权限清单和接口对账表。",
            "mechanism": "识别 ITAC 时，应沿着触发条件、输入数据、控制逻辑、参数或主数据、输出结果五个环节展开。例如，系统自动阻止超信用额度发货：客户信用额度与未结应收构成输入，额度比较规则构成逻辑，信用限额参数构成配置，拦截或审批提示构成输出。任一环节错误，控制的结果都可能失去意义。",
            "procedure": "先用业务语言界定风险和控制目标，再确认系统是否实际承担了该控制步骤。随后取得流程说明、配置或规则、样本输入输出、例外处理记录和期间内变更资料。对计算类控制，应选取可追溯的交易重算；对限制类控制，应观察不满足条件时系统是否拒绝、拦截或转入审批；对接口类控制，应分别验证完整性与准确性。",
            "evidence": "证据不能只是一张成功页面截图。应能说明系统名称、功能位置、参数取值、适用期间、交易或报表总体，以及测试所用输入与得到输出之间的对应关系。若依赖系统报表，还需验证报表来源、筛选条件、字段口径和生成逻辑，避免把未经验证的 IPE 当作可靠证据。",
            "pitfalls": ["不要将人工复核后才发现的问题误写成自动控制。", "不要只测试正常情形；控制通常在异常输入或临界条件下才体现价值。", "不要忽略程序、参数和主数据在期间内的变更；它们会改变控制逻辑。"],
        }
    if any(key in text for key in ("itgc", "权限", "账号", "变更", "备份", "日志", "sa/pm/ns")):
        return {
            "definition": "IT 一般控制（ITGC）是支持应用系统持续可靠运行的基础控制，包括访问权限、程序变更、运行维护、备份恢复和开发管理。它通常不直接计算金额，却决定应用控制和系统数据能否在整个期间内被持续信赖。",
            "mechanism": "以权限管理为例，申请、审批、开通、定期复核和离职停用共同构成闭环；任何一环缺失，都可能使未经授权的人员查看、修改或删除数据。以变更管理为例，需求、风险评估、测试、授权、部署和事后核验构成控制链，目的在于防止未经验证的程序或参数进入生产环境。",
            "procedure": "先确认系统边界、关键角色和控制频率，再按控制目标设计程序。权限测试通常需要总体用户清单、角色权限矩阵、申请审批记录、离职名单和定期复核证据；变更测试通常需要变更总体、样本选择依据、测试证据、审批记录和生产发布记录。备份控制除查看任务成功日志外，还应检查恢复测试是否覆盖数据、配置和关键功能。",
            "evidence": "审计证据应覆盖期间，而非只证明期末状态。系统导出的清单需要确认来源、生成日期、筛选条件和完整性；人工提供的台账需要与系统记录或其他独立来源交叉核对。对于例外，应取得发生时间、受影响范围、补偿措施和整改跟踪，而不是只记录“已处理”。",
            "pitfalls": ["期末没有异常账号，不等于全年离职停用和权限变更及时执行。", "一次备份成功不等于能够恢复；恢复测试才证明恢复目标可以实现。", "紧急变更可以适用例外流程，但仍应保留紧急性依据、必要授权和事后复核。"],
        }
    if any(key in text for key in ("数据", "caats", "sql", "交叉验证", "迁移")):
        return {
            "definition": "审计数据分析是用可复现的规则检查总体、识别异常并支持审计判断的过程。代码、表格或可视化只是工具；审计价值来自于分析问题、数据口径、关联逻辑和异常追溯是否与审计目标一致。",
            "mechanism": "一项分析至少包含总体、期间、业务主键、字段口径、规则和输出六个要素。例如核对接口完整性，需要先界定源系统和目标系统的交易总体、传输期间和唯一交易号，再比较笔数、金额、状态及异常重传记录。若用姓名而不是唯一标识关联数据，很容易出现同名匹配、重复匹配或遗漏匹配。",
            "procedure": "先把问题写成可验证的假设：要核查什么风险、预期结果是什么、异常如何定义。再取得原始数据并记录提取时间、总体范围、字段说明和数据版本。处理前检查空值、重复值、日期格式和主键唯一性；处理后用控制总额、抽样回查和异常追溯验证结果。最后将规则、参数、运行记录和异常清单保存在可复核位置。",
            "evidence": "分析结果应让复核人能够从异常记录回到源单据或系统交易，并重新运行同一规则得到相同结果。因此，最终底稿应保留输入文件标识、字段映射、关联条件、筛选参数、代码或操作步骤、控制总额和异常处置结论。仅保留截图或汇总金额，无法证明分析范围和规则是否正确。",
            "pitfalls": ["程序运行无报错，不代表口径或关联规则正确。", "异常是进一步核验的起点，不能直接等同于控制失效或错报。", "不要在没有确定总体和期间前先挑选异常；这样会使结论失去覆盖范围。"],
        }
    if any(key in text for key in ("业务", "财务", "收入", "科目", "认定", "制造", "存货", "采购", "销售")):
        return {
            "definition": "业务与财务链路描述一项业务从发起、授权、系统处理到会计记录和报表列报的全过程。审计人员理解链路，不是为了复述流程，而是为了定位可能导致错报的节点、识别相关系统和判断影响的科目与认定。",
            "mechanism": "以采购入库为例，采购订单、收货、质检、入库、暂估、发票匹配和付款共同影响存货、应付账款、成本和现金流。以销售收入为例，订单、发货、签收、开票、收入确认、收款和退货共同影响收入完整性、截止、应收账款计价和存货结转。系统接口、主数据和自动计算规则决定业务信息如何在各环节传递。",
            "procedure": "先从一笔真实业务开始，识别业务单据、责任岗位、系统功能、关键字段、触发时点和会计分录；再由分录追溯回业务事实，验证两条路径是否闭合。对于每个关键节点，写明可能发生的错误、现有控制以及可取得的证据。特别关注月末、跨期、退货、冲销、手工调整和异常审批，这些情形最容易影响认定。",
            "evidence": "有效的链路证据应能把业务单据、系统记录和会计结果一一对应。除查看流程图外，还应取得样本交易、系统字段截图或导出、接口或批处理记录、相关审批和总账凭证。若金额不一致，要先判断是期间差、汇率、税额、汇总层级还是实际异常，不能直接得出结论。",
            "pitfalls": ["不要把流程访谈当作已经验证的事实；访谈应由系统记录和样本交易印证。", "不要只核对总额；完整性、准确性、截止和授权往往需要不同证据。", "不要忽略异常路径，正常流程有效不能说明退货、冲销或手工调整也受控。"],
        }
    return {
        "definition": "审计判断建立在风险、控制目标、执行程序、证据和结论之间可追溯的联系上。底稿不是资料的堆放处，而是说明审计人员为何选择某项程序、取得了什么事实、如何评价例外以及结论边界在哪里的工作记录。",
        "mechanism": "风险决定控制目标，控制目标决定需要取得的证据，证据的性质和范围决定结论能够覆盖到什么程度。例如，若风险是未经授权的程序变更影响计算逻辑，控制目标是变更经测试和批准后才部署；程序就应检查变更总体、测试、审批和发布记录，而不是只看当前页面结果。",
        "procedure": "开始前先写清楚待回答的问题、总体范围、期间和评价标准。执行中区分已确认事实、待核实信息和管理层解释；发生例外时，确认其真实性、频率、影响范围和补偿控制。完成后检查底稿主体、期间、系统名称、索引、引用和结论是否一致，并横向关注同类问题是否存在于其他底稿。",
        "evidence": "每项关键判断都应有可定位的证据支撑：来源、日期、文件名称或系统路径、选样逻辑、关键字段以及与结论的关系。结论必须与测试范围、证据质量和例外评价匹配；资料不足时应明确限制，而不是用笼统措辞扩大结论。",
        "pitfalls": ["不要只修正文句或格式，而不追溯 Review 意见反映的根因。", "不要让结论超出样本、期间或证据能够支持的范围。", "不要遗漏例外事项和后续跟进，它们往往决定结论是否成立。"],
    }


def _task_courseware_html(task: DevelopmentTrainingTask, week: DevelopmentTrainingWeek, plan: DevelopmentTrainingPlan) -> str:
    title = html_escape(task.title or "学习任务")
    employee = html_escape(plan.employee_name or "学员")
    batch = html_escape(f"第 {week.week_no} 批：{week.title}")
    raw_objective = (week.objective or task.purpose or "").strip()
    objective = html_escape(raw_objective)
    raw_description = (task.description or "").strip()
    raw_instructions = (task.instructions or task.description or "").strip()
    description = html_escape(task.description or "")
    instructions = html_escape(task.instructions or task.description or "")
    criteria = html_escape(task.completion_criteria or "")
    concept, principle, risk = _courseware_reason(task)
    chapter = _courseware_chapter(task)
    def text(value: str) -> str:
        return html_escape(value).replace("\n", "<br>")
    pitfalls = "".join(f"<li>{text(item)}</li>" for item in chapter["pitfalls"])
    introduction_text = f"<p>{description}</p>" if raw_description != raw_instructions else ""
    objective_text = (
        f"<p>{objective}</p>"
        if raw_objective not in {raw_description, raw_instructions}
        else "<p>本节将围绕任务对应的风险、控制目标、证据要求和结论边界建立完整理解。</p>"
    )
    completion_text = (
        f"<p>{criteria}</p>"
        if (task.completion_criteria or "").strip() != (task.instructions or task.description or "").strip()
        else "<p>本任务的完成要求已在“学习要求”中列明。提交时应进一步说明所采用的程序、取得的事实、例外评价和结论边界。</p>"
    )
    task_application = '''<h2 data-chapter-key="walkthrough" data-chapter-module="任务推演">四、结合本任务进行推演</h2><h3>把要求拆成可执行问题</h3><p>将本节学习要求拆为四个问题：需要确认的业务或系统事实是什么；可能发生的错误是什么；现有控制如何预防或发现该错误；用什么资料能够证明控制在适用期间内实际运行。这样拆解后，工作不会停留在“收集资料”层面，而能形成清晰的测试逻辑。</p><h3>从一项事实走到一项结论</h3><p>先选择一笔具有代表性的业务、一次系统处理或一项配置作为切入点，沿着输入、处理、输出和后续核验追踪。记录交易或资料的唯一标识、发生日期、责任岗位、系统功能和关键字段。若发现结果与预期不一致，不应立即定性；需要先排除期间差异、汇总层级、主数据变化、例外审批或重处理等合理原因，再判断是否形成控制例外。</p><h3>判断范围而非只判断单点</h3><p>一个样本能证明该样本发生了什么，不能自动证明整个期间都有效。需要根据控制频率、总体数量、系统变更、异常情况和样本测试结果判断是否需要扩大程序。若控制依赖报表、接口或系统配置，也要分别评价这些依赖信息的完整性和准确性。这样得出的结论才能与证据范围相匹配。</p><h3>形成可复核的工作记录</h3><p>记录应使未参与现场工作的复核人能够理解判断过程。每一项引用应能定位到具体文件、系统页面、报表版本或交易编号；每一个结论应能回指到对应的程序和事实。对于口头访谈，应记录访谈对象、日期、关键陈述以及后续验证方式。对于系统截图，应同时说明截图反映的功能、参数、期间和与测试目标的关系，避免只有图片而没有证据含义。</p><p>当资料之间出现矛盾时，应优先回到原始业务记录和系统日志，分析差异是由取数时点、处理状态、汇总口径还是实际异常造成。将差异分析留在底稿中，能够说明项目组不是简单接受解释，而是完成了必要的核验。</p><p>完成初稿后，应以复核人的视角回读：不了解现场情况的人，能否仅依据本页记录识别业务背景、测试总体、所取证据、已发现例外以及结论边界。若其中任何一项无法定位，应补充引用或事实说明后再提交。对需要后续跟进的事项，应明确责任人、预计完成时间和复核方式，确保异常处理形成闭环。</p><div class="example"><strong>本任务输出应体现的结构</strong><p>先写风险和控制目标，再写程序与样本选择依据；随后列明取得的事实和例外；最后说明例外是否影响控制目标、是否存在补偿控制以及结论的适用范围。完成标准请以本课件末尾的“提交前自查”为准。</p></div>'''
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{title}｜学习课件</title><style>body{{max-width:920px;margin:0 auto;padding:42px 26px;font:16px/1.9 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#1f2937;background:#f8fafc}}main{{background:#fff;border:1px solid #dbe4ee;border-radius:14px;padding:38px;box-shadow:0 8px 24px rgba(15,23,42,.06)}}.meta{{color:#64748b;font-size:14px}}h1{{margin:10px 0 4px;color:#0f3f78}}h2{{margin-top:36px;padding-bottom:8px;border-bottom:1px solid #dbe4ee;color:#174f8a;font-size:20px}}h3{{margin:22px 0 6px;color:#334155;font-size:17px}}p{{margin:10px 0;white-space:pre-wrap}}li{{margin:9px 0}}.notice,.risk,.example{{margin:20px 0;padding:16px 18px;border-radius:6px}}.notice{{border-left:4px solid #d97706;background:#fffbeb}}.risk{{border-left:4px solid #b91c1c;background:#fef2f2}}.example{{border-left:4px solid #2563eb;background:#eff6ff}}.toc{{margin:22px 0;padding:16px 20px;background:#f1f5f9;border-radius:8px}}.toc li{{margin:3px 0}}</style></head><body><main><div class="meta">{employee} · {batch} · 专属学习课件</div><h1>{title}</h1><div class="toc"><strong>本节内容</strong><ol><li>本节定位与学习目标</li><li>核心概念与工作机制</li><li>审计程序与证据判断</li><li>任务推演与工作输出</li><li>注意事项、风险实质与自查</li></ol></div><h2 data-chapter-key="orientation" data-chapter-module="定位与目标">一、本节定位与学习目标</h2>{introduction_text}{objective_text}<div class="example"><strong>学习完成后应达到的程度</strong><p>不仅能够复述本节术语，还应能结合当前任务解释：风险发生在何处、系统或人员如何处理该风险、应取得哪些资料，以及这些资料为何能够支持审计判断。</p></div><h2 data-chapter-key="concept" data-chapter-module="核心概念">二、核心概念：{html_escape(concept)}</h2><h3>概念边界</h3><p>{text(chapter["definition"])}</p><h3>工作机制</h3><p>{text(chapter["mechanism"])}</p><p>{html_escape(principle)}</p><h2 data-chapter-key="practice" data-chapter-module="程序与证据">三、如何落实到审计工作</h2><h3>本任务的学习要求</h3><p>{instructions}</p><h3>推荐的执行顺序</h3><p>{text(chapter["procedure"])}</p><h3>证据应当回答什么问题</h3><p>{text(chapter["evidence"])}</p>{task_application}<div class="notice"><strong>注意事项</strong><ol>{pitfalls}<li>先确认资料来源、适用期间、总体范围和关键字段口径，再对结果作出判断。</li><li>区分已确认事实、管理层解释和审计结论；未取得的资料不能替代为既定事实。</li></ol></div><h2 data-chapter-key="risk" data-chapter-module="风险实质">五、风险实质与影响传导</h2><div class="risk"><strong>本节重点风险</strong><p>{html_escape(risk)}</p></div><p>风险的实质在于：关键处理、控制或数据传递一旦失效而未被及时发现，业务记录可能发生遗漏、重复、错误或未经授权的变动。该问题可能先表现为操作层面的异常，随后影响系统数据、会计记录、财务报表认定和审计结论。因此，审计程序既要识别异常，也要确认异常的范围、原因、补偿控制和最终影响。</p><h2 data-chapter-key="checklist" data-chapter-module="完成标准">六、完成标准与提交前自查</h2>{completion_text}<ol><li>能用自己的语言说明本任务对应的业务或系统环节，以及该环节要防范的错误。</li><li>能列明执行程序、资料来源、适用期间和关键判断，而不只列出资料名称。</li><li>能说明例外发生后应如何判断影响范围、取得补充证据并记录结论边界。</li><li>完成在线选择题后，逐题阅读答案与解析，再提交作业。</li></ol></main></body></html>'''


@training_router.get("/tasks/{task_id}/courseware")
def training_task_courseware(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> HTMLResponse:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    week = db.get(DevelopmentTrainingWeek, task.training_week_id)
    plan = db.get(DevelopmentTrainingPlan, week.training_plan_id) if week else None
    if week is None or plan is None:
        raise HTTPException(status_code=404, detail="培养任务关联计划不存在")
    record_learning_event(db, employee_id=user.id, event_type="courseware_opened", task=task, week=week, plan=plan, source="learner")
    db.commit()
    return HTMLResponse(_task_courseware_html(task, week, plan))


@training_router.get("/mentor/tasks/{task_id}")
def mentor_task_detail(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = db.get(DevelopmentTrainingTask, task_id)
    week = db.get(DevelopmentTrainingWeek, task.training_week_id) if task else None
    plan = db.get(DevelopmentTrainingPlan, week.training_plan_id) if week else None
    if task is None or week is None or plan is None:
        raise HTTPException(status_code=404, detail="培养任务不存在")
    if not _mentor_can_access_plan(plan, user):
        raise HTTPException(status_code=403, detail="无权查看该学员任务")
    return {"task": {"id": task.id, "taskCode": task.task_code, "title": task.title, "description": task.description, "purpose": task.purpose, "instructions": task.instructions, "completionCriteria": task.completion_criteria, "submissionRequirements": task.submission_requirements}, "employee": {"id": plan.employee_id, "code": plan.employee_code, "name": plan.employee_name}, "submissions": [_submission_payload(item) for item in sorted(task.submissions, key=lambda item: item.version)]}


@training_router.get("/tasks/{task_id}")
def training_task_detail(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    read_material_ids = {row.material_id for row in db.execute(select(DevelopmentLearningMaterialRead).where(DevelopmentLearningMaterialRead.employee_id == user.id, DevelopmentLearningMaterialRead.material_id.in_([item.id for item in task.materials]))).scalars().all()} if task.materials else set()
    submissions = sorted(task.submissions, key=lambda item: item.version)
    prerequisites = _prerequisite_payload(db, task)
    week = db.get(DevelopmentTrainingWeek, task.training_week_id)
    note = db.execute(select(DevelopmentTaskNote).where(DevelopmentTaskNote.task_id == task.id, DevelopmentTaskNote.employee_id == user.id)).scalar_one_or_none()
    courseware_notes = db.execute(
        select(DevelopmentCoursewareNote).where(
            DevelopmentCoursewareNote.task_id == task.id,
            DevelopmentCoursewareNote.employee_id == user.id,
        )
    ).scalars().all()
    unread_material_count = sum(1 for item in task.materials if item.id not in read_material_ids)
    return {
        "id": task.id, "taskCode": task.task_code, "title": task.title, "description": task.description,
        "purpose": task.purpose, "instructions": task.instructions, "taskType": task.task_type,
        "estimatedHours": task.estimated_hours, "startDate": task.start_date, "dueDate": task.due_date,
        "completionCriteria": task.completion_criteria, "submissionRequired": task.submission_required,
        "submissionType": task.submission_type, "submissionTitle": task.submission_title,
        "submissionRequirements": task.submission_requirements, "mentorReviewRequired": task.mentor_review_required,
        "status": task.status, "selfCheckQuestions": _public_task_questions(task),
        "questionCount": len(_task_questions(task)),
        "relatedSubmissionTask": _related_submission_task(task, week.tasks if week else []),
        "prerequisiteTaskIds": _prerequisite_ids(task), "prerequisites": prerequisites,
        "locked": bool(prerequisites), "lockedReason": "前置任务尚未完成" if prerequisites else None,
        "materials": [{"id": item.id, "title": item.title, "type": item.material_type, "courseScope": item.course_scope, "url": item.url, "description": item.description, "read": item.id in read_material_ids} for item in sorted(task.materials, key=lambda item: (item.sort_order, item.id))],
        "unreadMaterialCount": unread_material_count,
        "canCompleteLearning": not task.submission_required and task.status != "completed" and not prerequisites and unread_material_count == 0,
        "submissions": [_submission_payload(item) for item in submissions],
        "note": note.content if note else "",
        "coursewareNotes": chapter_payload(courseware_notes),
        "coursewareNoteModules": group_notes_by_module(chapter_payload(courseware_notes)),
    }


@training_router.put("/tasks/{task_id}/note")
def save_training_task_note(task_id: int, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    content = str(payload.get("content") or "").strip()
    note = db.execute(select(DevelopmentTaskNote).where(DevelopmentTaskNote.task_id == task.id, DevelopmentTaskNote.employee_id == user.id)).scalar_one_or_none()
    if note is None:
        note = DevelopmentTaskNote(task_id=task.id, employee_id=user.id, content=content)
        db.add(note)
    else:
        note.content = content
    if content:
        record_learning_event(db, employee_id=user.id, event_type="note_saved", task=task, source="learner", payload={"chars": len(content)})
    db.commit()
    return {"taskId": task.id, "content": note.content, "updatedAt": note.updated_at}


def _task_courseware_notes(db: Session, task_id: int, employee_id: int) -> list[DevelopmentCoursewareNote]:
    return db.execute(
        select(DevelopmentCoursewareNote).where(
            DevelopmentCoursewareNote.task_id == task_id,
            DevelopmentCoursewareNote.employee_id == employee_id,
        )
    ).scalars().all()


@training_router.get("/tasks/{task_id}/courseware-notes")
def list_courseware_notes(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    notes = chapter_payload(_task_courseware_notes(db, task.id, user.id))
    return {"taskId": task.id, "notes": notes, "modules": group_notes_by_module(notes)}


@training_router.put("/tasks/{task_id}/courseware-notes")
def save_courseware_note(task_id: int, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    chapter_key = str(payload.get("chapterKey") or payload.get("chapter_key") or "").strip()
    chapter = CHAPTER_BY_KEY.get(chapter_key)
    if chapter is None:
        raise HTTPException(status_code=400, detail="未知的课件章节")
    content = str(payload.get("content") or "")
    if len(content) > 8000:
        raise HTTPException(status_code=400, detail="单章笔记不能超过 8000 字")
    note = db.execute(
        select(DevelopmentCoursewareNote).where(
            DevelopmentCoursewareNote.task_id == task.id,
            DevelopmentCoursewareNote.employee_id == user.id,
            DevelopmentCoursewareNote.chapter_key == chapter_key,
        )
    ).scalar_one_or_none()
    if note is None:
        note = DevelopmentCoursewareNote(task_id=task.id, employee_id=user.id, chapter_key=chapter_key, content=content)
        db.add(note)
    else:
        note.content = content
    if content.strip():
        record_learning_event(
            db, employee_id=user.id, event_type="note_saved", task=task, source="learner",
            payload={"chars": len(content), "chapterKey": chapter_key},
        )
    db.commit()
    notes = chapter_payload(_task_courseware_notes(db, task.id, user.id))
    return {"taskId": task.id, "note": {"key": chapter_key, "title": chapter["title"], "module": chapter["module"], "content": note.content}, "notes": notes, "modules": group_notes_by_module(notes)}


@training_router.post("/tasks/{task_id}/materials/{material_id}/read")
def mark_training_material_read(task_id: int, material_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    material = db.get(DevelopmentLearningMaterial, material_id)
    if material is None or material.task_id != task.id:
        raise HTTPException(status_code=404, detail="学习材料不存在")
    row = db.execute(select(DevelopmentLearningMaterialRead).where(DevelopmentLearningMaterialRead.material_id == material.id, DevelopmentLearningMaterialRead.employee_id == user.id)).scalar_one_or_none()
    if row is None:
        row = DevelopmentLearningMaterialRead(material_id=material.id, employee_id=user.id, read_at=datetime.utcnow())
        db.add(row)
    else:
        row.read_at = datetime.utcnow()
    record_learning_event(db, employee_id=user.id, event_type="material_read", task=task, material_id=material.id, source="learner", payload={"materialTitle": material.title})
    db.commit()
    return {"materialId": material.id, "read": True, "readAt": row.read_at}


@training_router.post("/tasks/{task_id}/complete-learning")
def complete_learning_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Complete a non-submission task after its required learning materials are read."""
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    _ensure_task_unlocked(db, task)
    if task.submission_required:
        raise HTTPException(status_code=422, detail="需要提交作业的任务不能在此直接完成")
    if task.status == "completed":
        return {"taskId": task.id, "status": task.status, "completed": True}
    material_ids = [item.id for item in task.materials]
    read_ids = set()
    if material_ids:
        read_ids = set(db.execute(
            select(DevelopmentLearningMaterialRead.material_id).where(
                DevelopmentLearningMaterialRead.employee_id == user.id,
                DevelopmentLearningMaterialRead.material_id.in_(material_ids),
            )
        ).scalars().all())
    unread = [item.title for item in task.materials if item.id not in read_ids]
    if unread:
        raise HTTPException(status_code=409, detail={"message": "请先完成并标记全部学习材料。", "unreadMaterials": unread})
    task.status = "completed"
    record_learning_event(db, employee_id=user.id, event_type="learning_completed", task=task, source="learner")
    db.commit()
    return {"taskId": task.id, "status": task.status, "completed": True}


@training_router.post("/tasks/{task_id}/signals")
def record_training_task_signal(task_id: int, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Reserved client telemetry hook for later monthly-review evidence."""
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    event_type = str(payload.get("eventType") or "").strip()
    if event_type not in LEARNER_SIGNAL_TYPES:
        raise HTTPException(status_code=422, detail="eventType 仅支持 courseware_heartbeat 或 task_focus")
    duration = payload.get("durationSeconds")
    duration_seconds = None
    if duration not in (None, ""):
        try:
            duration_seconds = int(duration)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="durationSeconds 必须是整数") from exc
        if duration_seconds < 0:
            raise HTTPException(status_code=422, detail="durationSeconds 不能为负数")
    event = record_learning_event(
        db,
        employee_id=user.id,
        event_type=event_type,
        task=task,
        source="learner",
        duration_seconds=duration_seconds,
        payload={"context": str(payload.get("context") or "")[:200]},
    )
    db.commit()
    return {"recorded": True, "eventType": event_type, "eventId": event.id if event else None}


@training_router.post("/tasks/{task_id}/submit")
def submit_training_task(task_id: int, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    _ensure_task_unlocked(db, task)
    if not task.submission_required:
        raise HTTPException(status_code=422, detail="该任务不要求提交作业")
    questions = _task_questions(task)
    answers = payload.get("selfCheckAnswers") or {}
    missing, incorrect = _validate_task_questions(questions, answers)
    feedback = _question_feedback(questions, answers)
    if missing or incorrect:
        record_quiz_attempt(db, employee_id=user.id, task=task, questions=questions, answers=answers, feedback=feedback, passed_gate=False)
        db.commit()
        raise HTTPException(status_code=422, detail=_question_error(questions, answers, missing, incorrect))
    content = str(payload.get("content") or "").strip()
    attachment = str(payload.get("attachment") or "").strip()
    if attachment.startswith(_LEGACY_TRAINING_PREFIX):
        raise HTTPException(status_code=422, detail="培训附件必须通过受控文件上传接口提交")
    if not questions and not content and not attachment:
        raise HTTPException(status_code=422, detail="本作业尚未配置在线题目，请联系导师补充课程练习")
    version = max((row.version for row in task.submissions if row.employee_id == user.id), default=0) + 1
    submission = DevelopmentSubmission(task_id=task.id, employee_id=user.id, submission_type=str(payload.get("submissionType") or task.submission_type or "assignment"), content=content, attachment=attachment, self_check_answers=json.dumps(answers, ensure_ascii=False), submitted_at=datetime.utcnow(), version=version, status="submitted")
    db.add(submission)
    db.flush()
    if feedback:
        record_quiz_attempt(db, employee_id=user.id, task=task, questions=questions, answers=answers, feedback=feedback, passed_gate=True, submission_id=submission.id)
    record_learning_event(
        db,
        employee_id=user.id,
        event_type="task_submitted",
        task=task,
        submission_id=submission.id,
        source="learner",
        payload={"version": version, "contentChars": len(content), "hasAttachment": bool(attachment), "quizTotal": len(feedback), "quizCorrect": sum(1 for item in feedback if item.get("status") == "correct")},
    )
    task.status = "completed" if not task.mentor_review_required else "submitted"
    db.commit()
    db.refresh(submission)
    return {"message": f"V{version} 已提交", "submission": _submission_payload(submission), "taskStatus": task.status, "questionFeedback": feedback, "quiz": {"total": len(feedback), "correctCount": sum(1 for item in feedback if item["status"] == "correct")}}


@training_router.get("/submissions/{submission_id}/attachment")
def download_training_submission_attachment(
    submission_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FileResponse:
    ensure_feature_permission(db, user, "development", "view")
    submission = db.get(DevelopmentSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="作业提交不存在")
    task = db.get(DevelopmentTrainingTask, submission.task_id)
    week = db.get(DevelopmentTrainingWeek, task.training_week_id) if task else None
    plan = db.get(DevelopmentTrainingPlan, week.training_plan_id) if week else None
    if submission.employee_id != user.id and (plan is None or not _mentor_can_access_plan(plan, user)):
        raise HTTPException(status_code=403, detail="无权下载该培训附件")
    name = _private_submission_name(submission.attachment or "")
    if name is None:
        raise HTTPException(status_code=404, detail="该提交没有受控附件")
    path = (TRAINING_SUBMISSIONS_ROOT / name).resolve(strict=False)
    try:
        path.relative_to(TRAINING_SUBMISSIONS_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="培训附件路径无效") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="培训附件不存在")
    return FileResponse(path, filename=path.name)


@training_router.post("/submissions/{submission_id}/review")
def review_training_submission(submission_id: int, payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "edit")
    submission = db.get(DevelopmentSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="作业提交不存在")
    task = db.get(DevelopmentTrainingTask, submission.task_id)
    week = db.get(DevelopmentTrainingWeek, task.training_week_id) if task else None
    plan = db.get(DevelopmentTrainingPlan, week.training_plan_id) if week else None
    if plan is None or not _mentor_can_access_plan(plan, user):
        raise HTTPException(status_code=403, detail="只有经理及以上层级可以进行 Mentor Review")
    result = str(payload.get("result") or "").strip()
    comments = str(payload.get("comments") or "").strip()
    raw_score = payload.get("score")
    score: float | None = None
    if raw_score not in (None, ""):
        try:
            score = float(raw_score)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="评分必须是 0 到 100 之间的数字") from exc
        if not 0 <= score <= 100:
            raise HTTPException(status_code=422, detail="评分必须在 0 到 100 之间")
    if result not in {"passed", "revision_required"}:
        raise HTTPException(status_code=422, detail="result 必须为 passed 或 revision_required")
    if result == "revision_required" and not comments:
        raise HTTPException(status_code=422, detail="要求修改时必须填写 Review comments")
    review = DevelopmentSubmissionReview(submission_id=submission.id, reviewer_id=user.id, result=result, score=score, comments=comments, reviewed_at=datetime.utcnow())
    db.add(review)
    submission.status = "reviewed"
    if task:
        task.status = "completed" if result == "passed" else "needs_revision"
    record_learning_event(
        db,
        employee_id=submission.employee_id,
        event_type="review_recorded",
        task=task,
        submission_id=submission.id,
        source="mentor",
        skill_tag="quality",
        payload={"result": result, "score": score, "hasComments": bool(comments)},
    )
    db.commit()
    db.refresh(review)
    return {"message": "Review 已保存", "result": result, "taskStatus": task.status if task else None, "reviewId": review.id}


def _validate_for_user(db: Session, payload: Any) -> tuple[Optional[TrainingPlanDocument], Optional[User], Optional[User], list[dict[str, str]]]:
    document, errors = validate_training_plan_payload(payload)
    if document is None:
        return None, None, None, errors
    employee, mentor, people_errors = _resolve_people(db, document)
    return document, employee, mentor, errors + people_errors


@router.post("/validate")
def validate_import(payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Validate only. This endpoint never writes training-plan tables."""
    ensure_feature_permission(db, user, "development", "edit")
    _require_training_management(user)
    document, employee, mentor, errors = _validate_for_user(db, payload)
    if document is None:
        return {"valid": False, "schemaVersion": payload.get("schemaVersion") if isinstance(payload, dict) else None, "errors": errors, "preview": None}
    return {
        "valid": not errors,
        "schemaVersion": document.schema_version,
        "errors": errors,
        "preview": _preview(document, employee, mentor),
    }


@router.post("/preview")
def preview_import(payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Return the same validation result with a UI-friendly import summary."""
    ensure_feature_permission(db, user, "development", "edit")
    _require_training_management(user)
    document, employee, mentor, errors = _validate_for_user(db, payload)
    if document is None:
        return {"valid": False, "errors": errors, "preview": None}
    return {"valid": not errors, "errors": errors, "preview": _preview(document, employee, mentor)}


def _import_document(db: Session, document: TrainingPlanDocument, employee: User, mentor: Optional[User]) -> dict[str, Any]:
    duplicate = db.execute(
        select(DevelopmentTrainingPlan).where(
            DevelopmentTrainingPlan.employee_id == employee.id,
            DevelopmentTrainingPlan.period == document.plan.period,
        )
    ).scalars().first()
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"员工 {document.employee.code} 已存在周期 {document.plan.period} 的培养计划，未覆盖原计划。",
                "errors": [_error("plan.period", "同一员工同一周期已有计划", "duplicate_plan")],
                "existingPlanId": duplicate.id,
            },
        )

    source = training_plan_json(document)
    plan = DevelopmentTrainingPlan(
        employee_id=employee.id,
        employee_code=document.employee.code,
        employee_name=document.employee.name,
        schema_version=document.schema_version,
        source_json=json.dumps(source, ensure_ascii=False),
        plan_type=document.plan.plan_type,
        period=document.plan.period,
        title=document.plan.title,
        overall_goal=document.plan.overall_goal,
        start_date=document.plan.start_date,
        end_date=document.plan.end_date,
        status="draft",
        mentor_id=mentor.id if mentor else None,
    )
    db.add(plan)
    db.flush()

    task_ids_by_code: dict[str, int] = {}
    pending_prerequisites: list[tuple[DevelopmentTrainingTask, list[str]]] = []
    week_count = 0
    task_count = 0
    material_count = 0
    for week_index, week_payload in enumerate(document.weeks):
        week = DevelopmentTrainingWeek(
            training_plan_id=plan.id,
            week_no=week_payload.week_no,
            title=week_payload.title,
            objective=week_payload.objective,
            start_date=week_payload.start_date,
            end_date=week_payload.end_date,
            expected_deliverable=week_payload.expected_deliverable,
            sort_order=week_index,
        )
        db.add(week)
        db.flush()
        week_count += 1
        for task_index, task_payload in enumerate(week_payload.tasks):
            submission = task_payload.submission
            task = DevelopmentTrainingTask(
                training_week_id=week.id,
                task_code=task_payload.task_code,
                title=task_payload.title,
                description=task_payload.description,
                purpose=task_payload.purpose,
                instructions=task_payload.instructions,
                task_type=task_payload.task_type,
                start_date=task_payload.start_date,
                due_date=task_payload.due_date,
                estimated_hours=task_payload.estimated_hours,
                completion_criteria=task_payload.completion_criteria,
                self_check_questions=json.dumps([
                    item.model_dump() if isinstance(item, ProtocolQuizQuestion) else item
                    for item in task_payload.self_check_questions
                ], ensure_ascii=False),
                submission_required=submission.required,
                submission_type=submission.submission_type,
                submission_title=submission.title,
                submission_requirements=submission.requirements,
                mentor_review_required=task_payload.mentor_review_required,
                sort_order=task_index,
                status="not_started",
            )
            db.add(task)
            db.flush()
            task_ids_by_code[task.task_code] = task.id
            pending_prerequisites.append((task, task_payload.prerequisite_task_codes))
            task_count += 1
            db.add(DevelopmentLearningMaterial(
                task_id=task.id,
                title=f"{task.title}｜学习课件", material_type="itas_page", course_scope="personal",
                url=f"/api/development/tasks/{task.id}/courseware",
                description="完整介绍本任务的概念、学习要求、注意事项和风险实质。", sort_order=0,
            ))
            material_count += 1

    for task, prerequisite_codes in pending_prerequisites:
        task.prerequisite_task_ids = json.dumps([task_ids_by_code[code] for code in prerequisite_codes], ensure_ascii=False)

    assessment = DevelopmentMonthlyAssessment(
        training_plan_id=plan.id,
        employee_id=employee.id,
        period=document.plan.period,
        total_score=document.assessment.total_score,
        thresholds_json=json.dumps([item.model_dump(by_alias=True) for item in document.assessment.thresholds], ensure_ascii=False),
        status="draft",
    )
    db.add(assessment)
    db.flush()
    for index, dimension in enumerate(document.assessment.dimensions):
        db.add(DevelopmentAssessmentDimension(
            assessment_id=assessment.id,
            dimension_code=dimension.code,
            dimension_name=dimension.name,
            weight=dimension.weight,
            description=dimension.description,
            sort_order=index,
        ))

    return {
        "trainingPlanId": plan.id,
        "employeeId": employee.id,
        "employeeCode": document.employee.code,
        "schemaVersion": document.schema_version,
        "counts": {"weeks": week_count, "tasks": task_count, "learningMaterials": material_count, "assessmentDimensions": len(document.assessment.dimensions)},
        "status": plan.status,
    }


@router.post("/confirm")
def confirm_import(payload: dict[str, Any] = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Validate and then atomically import a complete training plan."""
    ensure_feature_permission(db, user, "development", "edit")
    _require_training_management(user)
    document, employee, mentor, errors = _validate_for_user(db, payload)
    if document is None or errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "培养计划未通过校验，未写入数据库。",
                "errors": errors,
            },
        )
    assert employee is not None
    try:
        result = _import_document(db, document, employee, mentor)
        db.commit()
        return {"success": True, "message": "培养计划已确认导入", "result": result}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "message": "培养计划导入失败，事务已回滚，数据库未保留半成品数据。",
                "errors": [_error("$", str(exc), "import_rollback")],
            },
        ) from exc
