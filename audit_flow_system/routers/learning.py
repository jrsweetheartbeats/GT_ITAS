from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import current_user, ensure_feature_permission, has_feature_permission
from ..models import AuditLog, PracticeQuestion, PracticeSubmission, TrainingWeek, User
from ..schemas import PracticeExecuteIn, PracticeReviewIn, PracticeSubmissionIn, PracticeValidateIn
from ..services.sql_practice_executor import execute_practice_sql
from ..services.audit_log import record_audit_log
from ..services.sql_practice_validator import validate_practice_result, validate_practice_sql


router = APIRouter(prefix="/api/learning", tags=["learning"])
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
ATTENDANCE_DAYS = 365


def _json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _can_review(user: User) -> bool:
    return bool(user.role and user.role.can_review)


def _submission_payload(row: PracticeSubmission) -> dict[str, Any]:
    return {
        "id": row.id,
        "questionId": row.question_id,
        "questionCode": row.question.code if row.question else "",
        "questionTitle": row.question.title if row.question else "",
        "userId": row.user_id,
        "username": row.user.username if row.user else "",
        "displayName": row.user.display_name if row.user else "",
        "attemptNo": row.attempt_no,
        "answerText": row.answer_text,
        "sqlText": row.sql_text,
        "status": row.status,
        "validationStatus": row.validation_status,
        "validation": _json(row.validation_json, {}),
        "score": row.score,
        "feedback": row.feedback,
        "submittedAt": row.submitted_at,
        "reviewedAt": row.reviewed_at,
        "updatedAt": row.updated_at,
    }


def _latest_submission(db: Session, question_id: int, user_id: int) -> Optional[PracticeSubmission]:
    return db.execute(
        select(PracticeSubmission)
        .where(PracticeSubmission.question_id == question_id, PracticeSubmission.user_id == user_id)
        .order_by(PracticeSubmission.attempt_no.desc(), PracticeSubmission.id.desc())
    ).scalars().first()


def _draft_for(db: Session, question: PracticeQuestion, user: User) -> PracticeSubmission:
    latest = _latest_submission(db, question.id, user.id)
    if latest is not None and latest.status == "draft":
        return latest
    attempt_no = (latest.attempt_no + 1) if latest is not None else 1
    row = PracticeSubmission(question_id=question.id, user_id=user.id, attempt_no=attempt_no)
    db.add(row)
    db.flush()
    return row


def _local_date(value: datetime) -> date:
    source = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return source.astimezone(LOCAL_TIMEZONE).date()


def _streaks(active_days: set[date], today: date) -> tuple[int, int]:
    current = 0
    cursor = today
    while cursor in active_days:
        current += 1
        cursor -= timedelta(days=1)
    longest = 0
    running = 0
    previous: Optional[date] = None
    for day in sorted(active_days):
        running = running + 1 if previous is not None and day == previous + timedelta(days=1) else 1
        longest = max(longest, running)
        previous = day
    return current, longest


def _question_attempt_stats(db: Session, question_ids: list[int]) -> dict[int, dict[int, dict[str, Any]]]:
    if not question_ids:
        return {}
    rows = db.execute(
        select(
            AuditLog.target_id,
            AuditLog.user_id,
            func.count(AuditLog.id),
            func.sum(case((AuditLog.success == True, 1), else_=0)),  # noqa: E712
            func.min(case((AuditLog.success == True, AuditLog.occurred_at), else_=None)),  # noqa: E712
        )
        .where(
            AuditLog.action == "practice_submission",
            AuditLog.target_type == "practice_question",
            AuditLog.target_id.in_(question_ids),
            AuditLog.user_id.is_not(None),
        )
        .group_by(AuditLog.target_id, AuditLog.user_id)
    ).all()
    output: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    for question_id, user_id, attempts, successes, first_success in rows:
        attempt_count = int(attempts or 0)
        success_count = int(successes or 0)
        output[int(question_id)][int(user_id)] = {
            "submissionCount": attempt_count,
            "errorCount": attempt_count - success_count,
            "successCount": success_count,
            "firstSuccessAt": first_success,
        }
    return output


def _question_ranking(
    stats: dict[int, dict[str, Any]],
    users: dict[int, User],
    current_user_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries = []
    for user_id, values in stats.items():
        person = users.get(user_id)
        if person is None:
            continue
        entries.append({
            "userId": user_id,
            "displayName": person.display_name or person.username,
            "submissionCount": values["submissionCount"],
            "errorCount": values["errorCount"],
            "successCount": values["successCount"],
            "firstSuccessAt": values["firstSuccessAt"],
            "isCurrentUser": user_id == current_user_id,
        })
    entries.sort(key=lambda item: (
        item["successCount"] <= 0,
        item["firstSuccessAt"] or datetime.max,
        item["errorCount"],
        item["submissionCount"],
        item["displayName"],
    ))
    rank = 0
    for item in entries:
        if item["successCount"] > 0:
            rank += 1
            item["rank"] = rank
        else:
            item["rank"] = None
        if item["firstSuccessAt"] is not None:
            first_success = item["firstSuccessAt"]
            if first_success.tzinfo is None:
                first_success = first_success.replace(tzinfo=timezone.utc)
            item["firstSuccessAt"] = first_success.isoformat()
    mine = stats.get(current_user_id, {})
    my_rank = next((item["rank"] for item in entries if item["userId"] == current_user_id), None)
    return entries, {
        "submissionCount": int(mine.get("submissionCount", 0)),
        "errorCount": int(mine.get("errorCount", 0)),
        "successCount": int(mine.get("successCount", 0)),
        "rank": my_rank,
    }


@router.get("/dashboard")
def learning_dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "learning", "view")
    today = datetime.now(LOCAL_TIMEZONE).date()
    calendar_start = today - timedelta(days=ATTENDANCE_DAYS - 1)
    utc_start = datetime.combine(calendar_start, datetime.min.time(), tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc).replace(tzinfo=None)
    login_times = db.execute(
        select(AuditLog.occurred_at).where(
            AuditLog.user_id == user.id,
            AuditLog.action == "login",
            AuditLog.success == True,  # noqa: E712
            AuditLog.occurred_at >= utc_start,
        )
    ).scalars().all()
    day_counts: dict[date, int] = defaultdict(int)
    for occurred_at in login_times:
        day_counts[_local_date(occurred_at)] += 1
    active_days = set(day_counts)
    current_streak, longest_streak = _streaks(active_days, today)

    stats_rows = db.execute(
        select(
            AuditLog.user_id,
            func.count(AuditLog.id),
            func.sum(case((AuditLog.success == True, 1), else_=0)),  # noqa: E712
            func.count(func.distinct(case((AuditLog.success == True, AuditLog.target_id), else_=None))),  # noqa: E712
        )
        .where(
            AuditLog.action == "practice_submission",
            AuditLog.target_type == "practice_question",
            AuditLog.user_id.is_not(None),
        )
        .group_by(AuditLog.user_id)
    ).all()
    stats_by_user = {
        int(user_id): {
            "submissionCount": int(attempts or 0),
            "successCount": int(successes or 0),
            "solvedCount": int(solved or 0),
        }
        for user_id, attempts, successes, solved in stats_rows
    }
    users = db.execute(select(User).where(User.status == "active").order_by(User.id)).scalars().all()
    overall = []
    for person in users:
        values = stats_by_user.get(person.id, {})
        overall.append({
            "userId": person.id,
            "displayName": person.display_name or person.username,
            "solvedCount": int(values.get("solvedCount", 0)),
            "isCurrentUser": person.id == user.id,
        })
    overall.sort(key=lambda item: (-item["solvedCount"], item["displayName"]))
    previous_score: Optional[int] = None
    previous_rank = 0
    for index, item in enumerate(overall, start=1):
        if previous_score is None or item["solvedCount"] != previous_score:
            previous_rank = index
        item["rank"] = previous_rank
        previous_score = item["solvedCount"]
    mine = stats_by_user.get(user.id, {})
    my_successes = int(mine.get("successCount", 0))
    my_submissions = int(mine.get("submissionCount", 0))
    return {
        "submissionSummary": {
            "submissionCount": my_submissions,
            "errorCount": my_submissions - my_successes,
            "successCount": my_successes,
            "solvedCount": int(mine.get("solvedCount", 0)),
            "rank": next((item["rank"] for item in overall if item["userId"] == user.id), None),
        },
        "attendance": {
            "calendarStart": calendar_start.isoformat(),
            "calendarEnd": today.isoformat(),
            "checkedInToday": today in active_days,
            "activeDayCount": len(active_days),
            "currentStreak": current_streak,
            "longestStreak": longest_streak,
            "days": [{"date": day.isoformat(), "count": count} for day, count in sorted(day_counts.items())],
        },
        "overallRanking": overall,
    }


@router.get("/weeks")
def list_weeks(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    ensure_feature_permission(db, user, "learning", "view")
    rows = db.execute(
        select(TrainingWeek).where(TrainingWeek.enabled == True).order_by(TrainingWeek.sort_order, TrainingWeek.id)  # noqa: E712
    ).scalars().all()
    output = []
    for week in rows:
        question_ids = [item.id for item in week.questions if item.enabled]
        completed = 0
        if question_ids:
            completed = db.execute(
                select(func.count(func.distinct(PracticeSubmission.question_id))).where(
                    PracticeSubmission.user_id == user.id,
                    PracticeSubmission.question_id.in_(question_ids),
                    PracticeSubmission.status.in_(["submitted", "reviewed"]),
                )
            ).scalar_one()
        output.append({
            "id": week.id,
            "code": week.code,
            "weekNo": week.week_no,
            "title": week.title,
            "summary": week.summary,
            "learningMarkdown": week.learning_markdown,
            "courseware": _json(week.courseware_json, []),
            "startsOn": week.starts_on,
            "dueAt": week.due_at,
            "questionCount": len(question_ids),
            "completedCount": completed,
        })
    return output


@router.get("/weeks/{week_id}")
def week_detail(
    week_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "learning", "view")
    week = db.get(TrainingWeek, week_id)
    if week is None or not week.enabled:
        raise HTTPException(status_code=404, detail="学习周不存在")
    questions = db.execute(
        select(PracticeQuestion)
        .where(PracticeQuestion.training_week_id == week.id, PracticeQuestion.enabled == True)  # noqa: E712
        .order_by(PracticeQuestion.sort_order, PracticeQuestion.id)
    ).scalars().all()
    attempt_stats = _question_attempt_stats(db, [question.id for question in questions])
    ranked_user_ids = {
        user_id
        for question_stats in attempt_stats.values()
        for user_id in question_stats
    }
    ranked_users = {
        person.id: person
        for person in db.execute(select(User).where(User.id.in_(ranked_user_ids))).scalars().all()
    } if ranked_user_ids else {}
    can_review = _can_review(user) and has_feature_permission(db, user, "learning", "manage")
    question_payload = []
    for question in questions:
        latest = _latest_submission(db, question.id, user.id)
        ranking, my_stats = _question_ranking(attempt_stats.get(question.id, {}), ranked_users, user.id)
        item = {
            "id": question.id,
            "code": question.code,
            "title": question.title,
            "prompt": question.prompt,
            "questionType": question.question_type,
            "projectScope": question.project_scope,
            "points": question.points,
            "validationRules": _json(question.validation_rules_json, {}),
            "latestSubmission": _submission_payload(latest) if latest else None,
            "ranking": ranking,
            "myStats": my_stats,
        }
        if can_review:
            item["answerGuidance"] = question.answer_guidance
        question_payload.append(item)
    return {
        "id": week.id,
        "code": week.code,
        "weekNo": week.week_no,
        "title": week.title,
        "summary": week.summary,
        "learningMarkdown": week.learning_markdown,
        "courseware": _json(week.courseware_json, []),
        "questions": question_payload,
        "canReview": can_review,
    }


@router.post("/questions/{question_id}/validate")
def validate_answer_sql(
    question_id: int,
    payload: PracticeValidateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "learning", "view")
    question = db.get(PracticeQuestion, question_id)
    if question is None or not question.enabled:
        raise HTTPException(status_code=404, detail="题目不存在")
    if question.question_type != "sql":
        return {"passed": True, "errors": [], "warnings": ["本题为文字题，无需SQL校验"], "checks": []}
    return validate_practice_sql(payload.sql_text, _json(question.validation_rules_json, {}))


@router.post("/questions/{question_id}/execute")
def execute_answer_sql(
    question_id: int,
    payload: PracticeExecuteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "learning", "view")
    question = db.get(PracticeQuestion, question_id)
    if question is None or not question.enabled:
        raise HTTPException(status_code=404, detail="题目不存在")
    if question.question_type != "sql":
        raise HTTPException(status_code=400, detail="本题不是SQL查询题")
    try:
        result = execute_practice_sql(payload.sql_text, _json(question.validation_rules_json, {}))
    except HTTPException as exc:
        record_audit_log(
            db, request, "practice_sql_execute", user=user, target_type="practice_question",
            target_id=question.id, success=False,
            details={"question_code": question.code, "submitted_sql": payload.sql_text, "error": exc.detail},
        )
        db.commit()
        raise
    record_audit_log(
        db, request, "practice_sql_execute", user=user, target_type="practice_question",
        target_id=question.id,
        details={
            "question_code": question.code,
            "submitted_sql": payload.sql_text,
            "row_count": result["rowCount"],
            "duration_ms": result["durationMs"],
            "limit_applied": result["limitApplied"],
        },
    )
    db.commit()
    return result


@router.put("/questions/{question_id}/submission")
def save_draft(
    question_id: int,
    payload: PracticeSubmissionIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "learning", "edit")
    question = db.get(PracticeQuestion, question_id)
    if question is None or not question.enabled:
        raise HTTPException(status_code=404, detail="题目不存在")
    row = _draft_for(db, question, user)
    row.answer_text = payload.answer_text.strip()
    row.sql_text = payload.sql_text.strip()
    row.validation_status = "pending"
    row.validation_json = "{}"
    db.commit()
    db.refresh(row)
    return _submission_payload(row)


@router.post("/questions/{question_id}/submit")
def submit_answer(
    question_id: int,
    payload: PracticeSubmissionIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "learning", "edit")
    question = db.get(PracticeQuestion, question_id)
    if question is None or not question.enabled:
        raise HTTPException(status_code=404, detail="题目不存在")
    row = _draft_for(db, question, user)
    row.answer_text = payload.answer_text.strip()
    row.sql_text = payload.sql_text.strip()
    if question.question_type == "sql":
        rules = _json(question.validation_rules_json, {})
        validation = validate_practice_sql(row.sql_text, rules)
        if validation["passed"] and rules.get("verify_execution") is True:
            try:
                execution = execute_practice_sql(row.sql_text, rules)
                result_validation = validate_practice_result(execution, rules)
            except HTTPException as exc:
                detail = exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)
                result_validation = {
                    "passed": False,
                    "errors": [f"实际执行未通过：{detail}"],
                    "warnings": [],
                    "checks": [{"name": "实际执行", "passed": False, "detail": str(detail)}],
                }
            validation["errors"].extend(result_validation["errors"])
            validation["warnings"].extend(result_validation["warnings"])
            validation["checks"].extend(result_validation["checks"])
            validation["passed"] = bool(validation["passed"] and result_validation["passed"])
    else:
        validation = {
            "passed": bool(row.answer_text),
            "errors": [] if row.answer_text else ["答案不能为空"],
            "warnings": [],
            "checks": [{"name": "答案完整性", "passed": bool(row.answer_text), "detail": "文字题不执行SQL"}],
        }
    row.validation_json = json.dumps(validation, ensure_ascii=False)
    row.validation_status = "passed" if validation["passed"] else "failed"
    if validation["passed"]:
        row.status = "submitted"
        row.submitted_at = datetime.utcnow()
    record_audit_log(
        db, request, "practice_submission", user=user, target_type="practice_question",
        target_id=question.id, success=bool(validation["passed"]),
        details={"question_code": question.code, "submitted_sql": row.sql_text, "attempt_no": row.attempt_no},
    )
    db.commit()
    db.refresh(row)
    result = _submission_payload(row)
    result["submitted"] = bool(validation["passed"])
    return result


@router.get("/submissions")
def list_submissions(
    week_id: Optional[int] = Query(default=None, alias="weekId"),
    user_id: Optional[int] = Query(default=None, alias="userId"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    ensure_feature_permission(db, user, "learning", "view")
    reviewer = _can_review(user) and has_feature_permission(db, user, "learning", "manage")
    query = select(PracticeSubmission).join(PracticeQuestion)
    if not reviewer:
        query = query.where(PracticeSubmission.user_id == user.id)
    elif user_id is not None:
        query = query.where(PracticeSubmission.user_id == user_id)
    if week_id is not None:
        query = query.where(PracticeQuestion.training_week_id == week_id)
    rows = db.execute(query.order_by(PracticeSubmission.updated_at.desc(), PracticeSubmission.id.desc())).scalars().all()
    return [_submission_payload(row) for row in rows]


@router.patch("/submissions/{submission_id}/review")
def review_submission(
    submission_id: int,
    payload: PracticeReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    ensure_feature_permission(db, user, "learning", "manage")
    if not _can_review(user):
        raise HTTPException(status_code=403, detail="当前角色不能批阅作业")
    row = db.get(PracticeSubmission, submission_id)
    if row is None:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    if row.status not in {"submitted", "reviewed"}:
        raise HTTPException(status_code=400, detail="草稿或校验失败的答案不能批阅")
    if payload.score > row.question.points:
        raise HTTPException(status_code=400, detail=f"本题最高{row.question.points}分")
    row.score = payload.score
    row.feedback = payload.feedback.strip()
    row.reviewer_user_id = user.id
    row.reviewed_at = datetime.utcnow()
    row.status = "reviewed"
    db.commit()
    db.refresh(row)
    return _submission_payload(row)
