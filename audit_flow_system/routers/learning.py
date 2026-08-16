from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import current_user, ensure_feature_permission, has_feature_permission
from ..models import PracticeQuestion, PracticeSubmission, TrainingWeek, User
from ..schemas import PracticeReviewIn, PracticeSubmissionIn, PracticeValidateIn
from ..services.sql_practice_validator import validate_practice_sql


router = APIRouter(prefix="/api/learning", tags=["learning"])


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
    can_review = _can_review(user) and has_feature_permission(db, user, "learning", "manage")
    question_payload = []
    for question in questions:
        latest = _latest_submission(db, question.id, user.id)
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
        validation = validate_practice_sql(row.sql_text, _json(question.validation_rules_json, {}))
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
