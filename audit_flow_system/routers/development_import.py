from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import secrets
import shutil
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.config import BASE_DIR, TRAINING_SUBMISSIONS_ROOT
from ..core.security import current_user, ensure_feature_permission, is_admin
from ..models import (
    DevelopmentAssessmentDimension,
    DevelopmentBlocker,
    DevelopmentEmployee,
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
from ..services.training_plan_protocol import (
    ProtocolQuizQuestion,
    TrainingPlanDocument,
    training_plan_json,
    validate_training_plan_payload,
)


router = APIRouter(prefix="/api/development/import", tags=["development-import"])
training_router = APIRouter(prefix="/api/development", tags=["development-training"])

# 执行人员只能访问自己的培养数据；经理及以上层级才可查看全员计划和导师工作台。
TRAINING_MANAGEMENT_ROLES = {"admin", "partner", "quality", "director", "senior_manager", "manager"}


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


def _learner_task_payload(task: DevelopmentTrainingTask, employee_id: int, today, prerequisites: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
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
        "relatedSubmissionTask": _related_submission_task(task),
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
    payloads = [_learner_task_payload(task, user.id, today, _prerequisite_payload(db, task)) for task in current_tasks]
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
        "tasks": payloads,
        "dailyTasks": agenda_tasks,
        "dailyAgenda": daily_agenda,
        "submissions": {"pending": pending_submissions, "required": required_submissions, "passed": passed, "revisionRequired": revision_required},
        "blockers": [{"id": item.id, "taskId": item.task_id, "problem": item.problem, "confirmedFacts": item.confirmed_facts, "materialsChecked": item.materials_checked, "initialJudgment": item.initial_judgment, "attemptedSolutions": item.attempted_solutions, "missingInformation": item.missing_information, "mentorQuestion": item.mentor_question, "blockerType": item.blocker_type, "selfAnalysisComplete": item.self_analysis_complete, "status": item.status, "mentorResponse": item.mentor_response, "resolutionAction": item.resolution_action, "createdAt": item.created_at, "resolvedAt": item.resolved_at, "durationDays": max(0, (item.resolved_at or datetime.now()).date().toordinal() - item.created_at.date().toordinal()) if item.created_at else None} for item in blockers],
        "metrics": {"completed": completed, "total": len(all_tasks), "completionRate": round(completed / len(all_tasks) * 100) if all_tasks else 0},
    }


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
        tasks = [task for week in plan.weeks for task in week.tasks]
        completed = sum(1 for task in tasks if task.status == "completed")
        overdue = [task for task in tasks if task.due_date and task.due_date < today and task.status not in {"completed", "blocked"}]
        pending_reviews = []
        for task in tasks:
            latest = _latest_submission(task, plan.employee_id)
            if task.mentor_review_required and latest and latest.status == "submitted":
                pending_reviews.append({"type": "review", "id": latest.id, "planId": plan.id, "taskId": task.id, "employeeName": plan.employee_name, "taskCode": task.task_code, "title": task.title, "dueDate": task.due_date})
        blockers = db.execute(select(DevelopmentBlocker).where(DevelopmentBlocker.employee_id == plan.employee_id, DevelopmentBlocker.task_id.in_([task.id for task in tasks]) if tasks else False, DevelopmentBlocker.status.in_(["open", "self_processing"]))).scalars().all()
        current_week = next((week for week in sorted(plan.weeks, key=lambda item: item.week_no) if week.start_date and week.end_date and week.start_date <= today <= week.end_date), None)
        assessment = next((item for item in plan.assessments if item.period == plan.period), None)
        students.append({"planId": plan.id, "employeeId": plan.employee_id, "employeeCode": plan.employee_code, "employeeName": plan.employee_name, "completionRate": round(completed / len(tasks) * 100) if tasks else 0, "overdueTasks": len(overdue), "pendingReview": len(pending_reviews), "blocked": len(blockers), "currentWeekNo": current_week.week_no if current_week else None, "period": plan.period, "assessmentStatus": assessment.status if assessment else "draft"})
        action_items.extend(pending_reviews)
        action_items.extend({"type": "blocker", "id": item.id, "planId": plan.id, "taskId": item.task_id, "employeeName": plan.employee_name, "title": item.problem, "createdAt": item.created_at} for item in blockers)
        action_items.extend({"type": "overdue", "id": task.id, "planId": plan.id, "taskId": task.id, "employeeName": plan.employee_name, "taskCode": task.task_code, "title": task.title, "dueDate": task.due_date} for task in overdue if task.submission_required or task.mentor_review_required)
        if assessment is not None and assessment.status in {"draft", "pending"} and plan.end_date and plan.end_date <= today:
            action_items.append({"type": "assessment", "id": assessment.id, "planId": plan.id, "employeeName": plan.employee_name, "period": plan.period, "title": f"{plan.period} 月度评价待评分"})
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
    return {"totalScore": assessment.total_score, "dimensions": [{"code": item.dimension_code, "name": item.dimension_name, "weight": item.weight, "score": item.score, "comments": item.comments} for item in sorted(assessment.dimensions, key=lambda item: item.sort_order)], "completedTasks": completed, "incompleteTasks": incomplete, "reviewHistory": reviews, "blockers": [_blocker_payload(item) for item in blockers], "mentorEvaluation": mentor_evaluation, "nextStageSuggestion": next_stage_suggestion}


def _weighted_assessment_total(dimensions: list[Any]) -> float:
    return round(sum((item.score or 0) * float(item.weight) / 100 for item in dimensions), 2)


@training_router.get("/mentor/plans/{plan_id}/assessment")
def mentor_assessment_detail(plan_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    plan = db.get(DevelopmentTrainingPlan, plan_id)
    if plan is None or not _mentor_can_access_plan(plan, user):
        raise HTTPException(status_code=404, detail="培养计划不存在或无权访问")
    assessment = _assessment_for_plan(db, plan)
    return {"plan": {"id": plan.id, "employeeCode": plan.employee_code, "employeeName": plan.employee_name, "period": plan.period, "title": plan.title}, "assessment": _assessment_payload(assessment)}


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
    assessment.summary = json.dumps(summary, ensure_ascii=False)
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
        lines = [f"# {plan.employee_name} {plan.period} 月度培养结果", f"- 总分：{assessment.total_score}", f"- Mentor评价：{summary.get('mentorEvaluation', '')}", f"- 下阶段建议：{summary.get('nextStageSuggestion', '')}", "", "## 能力维度"]
        lines.extend(f"- {item.get('name')}：{item.get('score')} / 100（权重 {item.get('weight')}%）" for item in summary.get("dimensions", []))
        lines.extend(["", "## 已完成任务"] + [f"- {item.get('taskCode')} {item.get('title')}" for item in summary.get("completedTasks", [])])
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


def _related_submission_task(task: DevelopmentTrainingTask) -> Optional[dict[str, Any]]:
    """Point a reading-only task at the actionable assignment in its week."""
    if task.submission_required or task.training_week is None:
        return None
    candidates = sorted(task.training_week.tasks, key=lambda item: (item.sort_order, item.id))
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


def _question_error(missing: list[Any], incorrect: list[Any]) -> dict[str, Any]:
    errors = []
    if missing:
        errors.append("请完成全部每日任务题目。")
    if incorrect:
        errors.append("选择题或填空题存在错误，必须全部答对后才能过关。")
    return {"message": " ".join(errors), "missingQuestions": missing, "incorrectQuestions": incorrect}


@training_router.get("/tasks/{task_id}")
def training_task_detail(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    read_material_ids = {row.material_id for row in db.execute(select(DevelopmentLearningMaterialRead).where(DevelopmentLearningMaterialRead.employee_id == user.id, DevelopmentLearningMaterialRead.material_id.in_([item.id for item in task.materials]))).scalars().all()} if task.materials else set()
    submissions = sorted(task.submissions, key=lambda item: item.version)
    prerequisites = _prerequisite_payload(db, task)
    note = db.execute(select(DevelopmentTaskNote).where(DevelopmentTaskNote.task_id == task.id, DevelopmentTaskNote.employee_id == user.id)).scalar_one_or_none()
    return {
        "id": task.id, "taskCode": task.task_code, "title": task.title, "description": task.description,
        "purpose": task.purpose, "instructions": task.instructions, "taskType": task.task_type,
        "estimatedHours": task.estimated_hours, "startDate": task.start_date, "dueDate": task.due_date,
        "completionCriteria": task.completion_criteria, "submissionRequired": task.submission_required,
        "submissionType": task.submission_type, "submissionTitle": task.submission_title,
        "submissionRequirements": task.submission_requirements, "mentorReviewRequired": task.mentor_review_required,
        "status": task.status, "selfCheckQuestions": _public_task_questions(task),
        "questionCount": len(_task_questions(task)),
        "relatedSubmissionTask": _related_submission_task(task),
        "prerequisiteTaskIds": _prerequisite_ids(task), "prerequisites": prerequisites,
        "locked": bool(prerequisites), "lockedReason": "前置任务尚未完成" if prerequisites else None,
        "materials": [{"id": item.id, "title": item.title, "type": item.material_type, "courseScope": item.course_scope, "url": item.url, "description": item.description, "read": item.id in read_material_ids} for item in sorted(task.materials, key=lambda item: (item.sort_order, item.id))],
        "submissions": [_submission_payload(item) for item in submissions],
        "note": note.content if note else "",
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
    db.commit()
    return {"taskId": task.id, "content": note.content, "updatedAt": note.updated_at}


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
    db.commit()
    return {"materialId": material.id, "read": True, "readAt": row.read_at}


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
    if missing or incorrect:
        raise HTTPException(status_code=422, detail=_question_error(missing, incorrect))
    content = str(payload.get("content") or "").strip()
    attachment = str(payload.get("attachment") or "").strip()
    if attachment.startswith(_LEGACY_TRAINING_PREFIX):
        raise HTTPException(status_code=422, detail="培训附件必须通过受控文件上传接口提交")
    if not content and not attachment:
        raise HTTPException(status_code=422, detail="请填写文本内容、文件地址或链接后再提交")
    version = max((row.version for row in task.submissions if row.employee_id == user.id), default=0) + 1
    submission = DevelopmentSubmission(task_id=task.id, employee_id=user.id, submission_type=str(payload.get("submissionType") or task.submission_type or "assignment"), content=content, attachment=attachment, self_check_answers=json.dumps(answers, ensure_ascii=False), submitted_at=datetime.utcnow(), version=version, status="submitted")
    db.add(submission)
    task.status = "completed" if not task.mentor_review_required else "submitted"
    db.commit()
    db.refresh(submission)
    return {"message": f"V{version} 已提交", "submission": _submission_payload(submission), "taskStatus": task.status}


@training_router.post("/tasks/{task_id}/submit-file")
async def submit_training_task_file(task_id: int, file: UploadFile = File(...), content: str = Form(""), self_check_answers: str = Form("{}"), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    ensure_feature_permission(db, user, "development", "view")
    task = _owned_training_task(db, task_id, user.id)
    _ensure_task_unlocked(db, task)
    if not task.submission_required:
        raise HTTPException(status_code=422, detail="该任务不要求提交作业")
    questions = _task_questions(task)
    answers = json.loads(self_check_answers or "{}")
    missing, incorrect = _validate_task_questions(questions, answers)
    if missing or incorrect:
        raise HTTPException(status_code=422, detail=_question_error(missing, incorrect))
    suffix = Path(file.filename or "attachment.bin").suffix[:16]
    target_dir = TRAINING_SUBMISSIONS_ROOT
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{user.id}_{task.id}_{secrets.token_hex(8)}{suffix}"
    target = target_dir / target_name
    target.write_bytes(await file.read())
    version = max((row.version for row in task.submissions if row.employee_id == user.id), default=0) + 1
    submission = DevelopmentSubmission(task_id=task.id, employee_id=user.id, submission_type="file", content=content.strip(), attachment=f"{_PRIVATE_TRAINING_PREFIX}{target_name}", self_check_answers=json.dumps(answers, ensure_ascii=False), submitted_at=datetime.utcnow(), version=version, status="submitted")
    db.add(submission)
    task.status = "completed" if not task.mentor_review_required else "submitted"
    db.commit()
    db.refresh(submission)
    return {"message": f"V{version} 已提交", "submission": _submission_payload(submission), "taskStatus": task.status}


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
    if result not in {"passed", "revision_required"}:
        raise HTTPException(status_code=422, detail="result 必须为 passed 或 revision_required")
    if result == "revision_required" and not comments:
        raise HTTPException(status_code=422, detail="要求修改时必须填写 Review comments")
    review = DevelopmentSubmissionReview(submission_id=submission.id, reviewer_id=user.id, result=result, score=payload.get("score"), comments=comments, reviewed_at=datetime.utcnow())
    db.add(review)
    submission.status = "reviewed"
    if task:
        task.status = "completed" if result == "passed" else "needs_revision"
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
            for material_index, material_payload in enumerate(task_payload.learning_materials):
                db.add(DevelopmentLearningMaterial(
                    task_id=task.id,
                    title=material_payload.title,
                    material_type=material_payload.material_type,
                    course_scope=material_payload.course_scope,
                    url=material_payload.url,
                    description=material_payload.description,
                    sort_order=material_index,
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
