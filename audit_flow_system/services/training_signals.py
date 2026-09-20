"""Learning-signal ledger for later personal monthly reviews.

These records are append-only evidence, not scores. Mentors still judge;
the ledger supplies objective traces from submissions, quizzes, blockers,
and engagement so each learner's next review is not only self-report.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from hashlib import sha1
import json
import re
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    DevelopmentBlocker,
    DevelopmentLearningEvent,
    DevelopmentQuizItemResult,
    DevelopmentTrainingPlan,
    DevelopmentTrainingTask,
    DevelopmentTrainingWeek,
)


CONTEXT_PROMPT_PREFIX = re.compile(r"^在[“\"][^”\"]+[”\"]这一节的学习情境中，")
DEBOUNCE_SECONDS = {
    "task_opened": 1800,
    "courseware_opened": 600,
    "material_read": 60,
    "note_saved": 120,
    "courseware_heartbeat": 120,
    "task_focus": 300,
}
LEARNER_SIGNAL_TYPES = {"courseware_heartbeat", "task_focus"}
TOPIC_DEFAULT_SKILL = {
    "finance": "financial_audit",
    "itgc": "itgc",
    "itac": "itac",
    "data": "data_analysis",
    "quality": "quality",
}
KNOWLEDGE_SKILL_TAGS = {
    "finance.balance_sheet_point_in_time": "financial_audit",
    "finance.revenue_interface_completeness": "mapping",
    "finance.credit_sales_ar": "financial_audit",
    "finance.scope_material_systems": "scope",
    "finance.business_to_assertion_chain": "mapping",
    "finance.profit_without_cash": "financial_audit",
    "itgc.sa_access_lifecycle": "itgc",
    "itgc.backup_vs_restore": "itgc",
    "itgc.change_evidence_chain": "itgc",
    "itgc.period_vs_period_end": "itgc",
    "itgc.interface_failure_monitoring": "itgc",
    "itgc.emergency_change": "itgc",
    "itac.automated_control_period": "itac",
    "itac.interface_cia": "interface_ipe",
    "itac.ipe_definition": "interface_ipe",
    "itac.report_as_evidence": "evidence",
    "itac.retransmission_without_recon": "interface_ipe",
    "itac.parameter_change_control": "itac",
    "data.define_population_first": "data_analysis",
    "data.join_key_quality": "data_analysis",
    "data.reproducibility": "quality",
    "data.exception_traceability": "evidence",
    "data.runnable_not_correct": "data_analysis",
    "data.ai_output_verification": "data_analysis",
    "quality.review_root_cause": "quality",
    "quality.conclusion_supported": "evidence",
    "quality.amount_not_parameters": "evidence",
    "quality.exception_scope": "exception_judgment",
    "quality.design_without_template": "procedure_design",
    "quality.reviewable_workpaper": "quality",
}
SKILL_TO_COMPETENCY = {
    "financial_audit": "financial_audit",
    "process_understanding": "financial_audit",
    "scope": "financial_audit",
    "itgc": "itgc",
    "itac": "itac",
    "interface_ipe": "interface_ipe",
    "data_analysis": "data_analysis",
    "evidence": "communication",
    "exception_judgment": "itac",
    "mapping": "financial_audit",
    "procedure_design": "project_management",
    "quality": "communication",
    "independence": "project_management",
}
REVIEW_HINT_CATALOG = [
    {"code": "B_process", "label": "业务流程理解", "skillTags": ["process_understanding"]},
    {"code": "B_finance", "label": "财务报表审计逻辑", "skillTags": ["financial_audit"]},
    {"code": "B_scope", "label": "IT审计范围 / 审计目标", "skillTags": ["scope"]},
    {"code": "B_itac", "label": "ITAC / 自动控制", "skillTags": ["itac"]},
    {"code": "B_itgc", "label": "ITGC / GC", "skillTags": ["itgc"]},
    {"code": "B_interface", "label": "接口 / IPE", "skillTags": ["interface_ipe"]},
    {"code": "B_data", "label": "数据分析 / CAATs", "skillTags": ["data_analysis"]},
    {"code": "B_evidence", "label": "审计证据充分性与适当性", "skillTags": ["evidence"]},
    {"code": "B_exception", "label": "异常定性与完整结论", "skillTags": ["exception_judgment"]},
    {"code": "B_mapping", "label": "IT问题映射到业务 / 科目 / 认定", "skillTags": ["mapping"]},
    {"code": "B_procedure", "label": "独立设计测试程序", "skillTags": ["procedure_design"]},
    {"code": "B_independence", "label": "独立推进与卡点处理", "skillTags": ["independence"]},
]


def plan_context(db: Session, task: Optional[DevelopmentTrainingTask]) -> tuple[Optional[DevelopmentTrainingWeek], Optional[DevelopmentTrainingPlan]]:
    if task is None:
        return None, None
    week = db.get(DevelopmentTrainingWeek, task.training_week_id)
    plan = db.get(DevelopmentTrainingPlan, week.training_plan_id) if week else None
    return week, plan


def infer_task_topic(task: DevelopmentTrainingTask, week: Optional[DevelopmentTrainingWeek] = None) -> str:
    text = f"{getattr(week, 'title', '')} {getattr(week, 'objective', '')} {task.title} {task.description} {task.purpose}".lower()
    if any(key in text for key in ("itac", "ipe", "interface", "接口", "自动控制", "自动计算")):
        return "itac"
    if any(key in text for key in ("itgc", "权限", "技术地图", "备份", "日志", "sa/pm/ns", "系统取证", "访问管理", "变更")):
        return "itgc"
    if any(key in text for key in ("caats", "代码", "数据", "sql", "交叉验证", "审计化", "数据技术")):
        return "data"
    if any(key in text for key in ("业务", "财审", "会计", "制造", "收入", "三大报表", "科目", "存货", "采购", "销售")):
        return "finance"
    return "quality"


def canonical_prompt(prompt: str) -> str:
    text = CONTEXT_PROMPT_PREFIX.sub("", str(prompt or "").strip())
    return "".join(text.split()).casefold()


def question_fingerprint(prompt: str) -> str:
    return sha1(canonical_prompt(prompt).encode("utf-8")).hexdigest()[:20]


def question_knowledge_key(question: dict[str, Any], fingerprint: str) -> str:
    return str(question.get("knowledgeKey") or question.get("knowledge_key") or fingerprint)[:80]


def question_skill_tag(question: dict[str, Any], task_topic: str) -> str:
    knowledge_key = str(question.get("knowledgeKey") or question.get("knowledge_key") or "")
    if knowledge_key in KNOWLEDGE_SKILL_TAGS:
        return KNOWLEDGE_SKILL_TAGS[knowledge_key]
    topic = str(question.get("topic") or task_topic or "quality")
    if knowledge_key.endswith(".task_start"):
        return "procedure_design"
    return TOPIC_DEFAULT_SKILL.get(topic, "quality")


def competency_for_skill(skill_tag: str) -> str:
    return SKILL_TO_COMPETENCY.get(skill_tag, "")


def suggested_score_1_to_5(accuracy: Optional[float], first_pass_rate: Optional[float] = None) -> Optional[int]:
    if accuracy is None:
        return None
    bonus = 0.05 if (first_pass_rate or 0) >= 0.7 else 0
    value = accuracy + bonus
    if value >= 0.9:
        return 5
    if value >= 0.75:
        return 4
    if value >= 0.55:
        return 3
    if value >= 0.35:
        return 2
    return 1


def _recent_event(db: Session, employee_id: int, event_type: str, task_id: Optional[int]) -> Optional[DevelopmentLearningEvent]:
    stmt = select(DevelopmentLearningEvent).where(
        DevelopmentLearningEvent.employee_id == employee_id,
        DevelopmentLearningEvent.event_type == event_type,
    )
    if task_id is not None:
        stmt = stmt.where(DevelopmentLearningEvent.task_id == task_id)
    return db.execute(stmt.order_by(DevelopmentLearningEvent.occurred_at.desc(), DevelopmentLearningEvent.id.desc()).limit(1)).scalars().first()


def record_learning_event(
    db: Session,
    *,
    employee_id: int,
    event_type: str,
    task: Optional[DevelopmentTrainingTask] = None,
    week: Optional[DevelopmentTrainingWeek] = None,
    plan: Optional[DevelopmentTrainingPlan] = None,
    submission_id: Optional[int] = None,
    material_id: Optional[int] = None,
    skill_tag: str = "",
    source: str = "system",
    duration_seconds: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
    occurred_at: Optional[datetime] = None,
) -> Optional[DevelopmentLearningEvent]:
    debounce = DEBOUNCE_SECONDS.get(event_type)
    now = occurred_at or datetime.utcnow()
    if debounce:
        previous = _recent_event(db, employee_id, event_type, task.id if task else None)
        if previous and previous.occurred_at and now - previous.occurred_at < timedelta(seconds=debounce):
            return previous
    if task and (week is None or plan is None):
        week, plan = plan_context(db, task)
    topic = infer_task_topic(task, week) if task else ""
    resolved_skill = skill_tag or TOPIC_DEFAULT_SKILL.get(topic, "")
    row = DevelopmentLearningEvent(
        employee_id=employee_id,
        training_plan_id=plan.id if plan else None,
        training_week_id=week.id if week else None,
        task_id=task.id if task else None,
        submission_id=submission_id,
        material_id=material_id,
        event_type=event_type[:80],
        skill_tag=resolved_skill[:80],
        competency_code=competency_for_skill(resolved_skill)[:80],
        source=source[:40],
        duration_seconds=duration_seconds,
        payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
        occurred_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _grade_stored_answers(questions: list[Any], answers: Any) -> list[dict[str, Any]]:
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
        })
    return feedback


def _next_quiz_attempt_no(db: Session, employee_id: int, task_id: int) -> int:
    current = db.execute(
        select(func.max(DevelopmentQuizItemResult.attempt_no)).where(
            DevelopmentQuizItemResult.employee_id == employee_id,
            DevelopmentQuizItemResult.task_id == task_id,
        )
    ).scalar()
    return int(current or 0) + 1


def record_quiz_attempt(
    db: Session,
    *,
    employee_id: int,
    task: DevelopmentTrainingTask,
    questions: list[Any],
    answers: Any,
    feedback: list[dict[str, Any]],
    passed_gate: bool,
    submission_id: Optional[int] = None,
) -> int:
    week, plan = plan_context(db, task)
    topic = infer_task_topic(task, week)
    attempt_no = _next_quiz_attempt_no(db, employee_id, task.id)
    answers = answers if isinstance(answers, dict) else {}
    now = datetime.utcnow()
    incorrect_keys: list[str] = []
    for item in feedback:
        index = int(item.get("index") or 0)
        question = questions[index] if index < len(questions) and isinstance(questions[index], dict) else {}
        prompt = str(item.get("prompt") or question.get("prompt") or f"第{index + 1}题")
        fingerprint = question_fingerprint(prompt)
        knowledge_key = question_knowledge_key(question, fingerprint)
        skill_tag = question_skill_tag(question, topic)
        status = str(item.get("status") or "incorrect")
        if status != "correct":
            incorrect_keys.append(knowledge_key)
        db.add(DevelopmentQuizItemResult(
            employee_id=employee_id,
            training_plan_id=plan.id if plan else None,
            task_id=task.id,
            submission_id=submission_id,
            question_index=index,
            question_fingerprint=fingerprint,
            knowledge_key=knowledge_key,
            prompt=prompt,
            skill_tag=skill_tag,
            competency_code=competency_for_skill(skill_tag),
            status=status,
            submitted_answer_json=json.dumps(item.get("submittedAnswer"), ensure_ascii=False, default=str),
            correct_answer_json=json.dumps(item.get("correctAnswer"), ensure_ascii=False, default=str),
            attempt_no=attempt_no,
            passed_gate=passed_gate,
            occurred_at=now,
        ))
    correct_count = sum(1 for item in feedback if item.get("status") == "correct")
    record_learning_event(
        db,
        employee_id=employee_id,
        event_type="quiz_attempted",
        task=task,
        week=week,
        plan=plan,
        submission_id=submission_id,
        skill_tag=TOPIC_DEFAULT_SKILL.get(topic, "quality"),
        payload={
            "attemptNo": attempt_no,
            "passedGate": passed_gate,
            "total": len(feedback),
            "correctCount": correct_count,
            "incorrectKnowledgeKeys": incorrect_keys,
            "answerKeys": sorted(str(key) for key in answers.keys()),
        },
    )
    return attempt_no


def backfill_quiz_results_from_submissions(db: Session, plan: DevelopmentTrainingPlan) -> int:
    """Persist historical passing submissions that predate the quiz ledger."""
    created = 0
    for week in plan.weeks:
        for task in week.tasks:
            questions = []
            try:
                questions = json.loads(task.self_check_questions or "[]")
            except (TypeError, ValueError):
                questions = []
            if not isinstance(questions, list) or not questions:
                continue
            for submission in sorted(task.submissions, key=lambda item: item.version):
                exists = db.execute(
                    select(DevelopmentQuizItemResult.id).where(DevelopmentQuizItemResult.submission_id == submission.id).limit(1)
                ).scalar()
                if exists:
                    continue
                try:
                    answers = json.loads(submission.self_check_answers or "{}")
                except (TypeError, ValueError):
                    answers = {}
                if not answers:
                    continue
                feedback = _grade_stored_answers(questions, answers)
                if not feedback:
                    continue
                passed = all(item.get("status") == "correct" for item in feedback)
                record_quiz_attempt(
                    db,
                    employee_id=submission.employee_id,
                    task=task,
                    questions=questions,
                    answers=answers,
                    feedback=feedback,
                    passed_gate=passed,
                    submission_id=submission.id,
                )
                created += 1
    return created


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _event_counts(events: list[DevelopmentLearningEvent]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        counts[event.event_type] += 1
    return dict(counts)


def build_review_evidence(db: Session, plan: DevelopmentTrainingPlan) -> dict[str, Any]:
    """Aggregate objective traces a later monthly-review generator can cite."""
    backfill_quiz_results_from_submissions(db, plan)
    tasks = [task for week in plan.weeks for task in week.tasks]
    task_ids = [task.id for task in tasks]
    today = datetime.now().date()
    events = db.execute(
        select(DevelopmentLearningEvent).where(
            DevelopmentLearningEvent.employee_id == plan.employee_id,
            DevelopmentLearningEvent.training_plan_id == plan.id,
        ).order_by(DevelopmentLearningEvent.occurred_at.asc(), DevelopmentLearningEvent.id.asc())
    ).scalars().all()
    quiz_rows = db.execute(
        select(DevelopmentQuizItemResult).where(
            DevelopmentQuizItemResult.employee_id == plan.employee_id,
            DevelopmentQuizItemResult.training_plan_id == plan.id,
        ).order_by(DevelopmentQuizItemResult.occurred_at.asc(), DevelopmentQuizItemResult.id.asc())
    ).scalars().all()
    blockers = []
    if task_ids:
        blockers = db.execute(
            select(DevelopmentBlocker).where(
                DevelopmentBlocker.employee_id == plan.employee_id,
                DevelopmentBlocker.task_id.in_(task_ids),
            )
        ).scalars().all()
    submissions = [item for task in tasks for item in task.submissions]
    reviews = [review for submission in submissions for review in submission.reviews]
    completed = [task for task in tasks if task.status == "completed"]
    overdue = [task for task in tasks if task.due_date and task.due_date < today and task.status not in {"completed", "blocked"}]
    on_time = [
        task for task in completed
        if not task.due_date or any(
            submission.submitted_at and submission.submitted_at.date() <= task.due_date
            for submission in task.submissions
        ) or (not task.submission_required)
    ]

    attempts: dict[tuple[int, int], list[DevelopmentQuizItemResult]] = defaultdict(list)
    for row in quiz_rows:
        attempts[(row.task_id, row.attempt_no)].append(row)
    first_pass_tasks: set[int] = set()
    attempted_tasks: set[int] = set()
    for (task_id, attempt_no), rows in attempts.items():
        if not rows:
            continue
        attempted_tasks.add(task_id)
        passed = all(item.status == "correct" for item in rows) or any(item.passed_gate for item in rows)
        if passed and attempt_no == 1:
            first_pass_tasks.add(task_id)
    first_pass = len(first_pass_tasks)
    first_pass_rate = _rate(first_pass, len(attempted_tasks))
    skill_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"answered": 0, "correct": 0, "incorrect": 0})
    wrong_items: dict[str, dict[str, Any]] = {}
    latest_by_knowledge: dict[str, DevelopmentQuizItemResult] = {}
    for row in quiz_rows:
        latest_by_knowledge[row.knowledge_key] = row
        stats = skill_stats[row.skill_tag or "quality"]
        stats["answered"] += 1
        if row.status == "correct":
            stats["correct"] += 1
        else:
            stats["incorrect"] += 1
            bucket = wrong_items.setdefault(row.knowledge_key, {
                "knowledgeKey": row.knowledge_key,
                "skillTag": row.skill_tag,
                "prompt": row.prompt,
                "wrongCount": 0,
                "lastStatus": row.status,
            })
            bucket["wrongCount"] += 1
            bucket["lastStatus"] = row.status
    still_wrong = [
        item for key, item in wrong_items.items()
        if latest_by_knowledge.get(key) is not None and latest_by_knowledge[key].status != "correct"
    ]
    capabilities = []
    for skill_tag, stats in sorted(skill_stats.items()):
        accuracy = _rate(stats["correct"], stats["answered"])
        capabilities.append({
            "skillTag": skill_tag,
            "competencyCode": competency_for_skill(skill_tag),
            "answered": stats["answered"],
            "correct": stats["correct"],
            "incorrect": stats["incorrect"],
            "accuracy": accuracy,
            "suggestedScore1to5": suggested_score_1_to_5(accuracy, first_pass_rate),
        })
    review_hints = []
    capability_by_skill = {item["skillTag"]: item for item in capabilities}
    for hint in REVIEW_HINT_CATALOG:
        matched = [capability_by_skill[tag] for tag in hint["skillTags"] if tag in capability_by_skill]
        if not matched:
            continue
        answered = sum(item["answered"] for item in matched)
        correct = sum(item["correct"] for item in matched)
        accuracy = _rate(correct, answered)
        wrong = [item for item in still_wrong if item["skillTag"] in hint["skillTags"]]
        note_parts = [f"选择题正确率 {round((accuracy or 0) * 100)}%（{correct}/{answered}）"]
        if wrong:
            note_parts.append(f"仍未过关 {len(wrong)} 题")
        review_hints.append({
            "module": "B",
            "code": hint["code"],
            "label": hint["label"],
            "objectiveNote": "；".join(note_parts),
            "suggestedScore1to5": suggested_score_1_to_5(accuracy),
            "hasData": True,
        })
    revision_required = sum(1 for review in reviews if review.result == "revision_required")
    passed_reviews = sum(1 for review in reviews if review.result == "passed")
    versions = [max((item.version for item in task.submissions), default=0) for task in tasks if task.submissions]
    blocker_types: dict[str, int] = defaultdict(int)
    for blocker in blockers:
        blocker_types[blocker.blocker_type or "general"] += 1
    event_counts = _event_counts(events)
    independence_proxy = {
        "completedWithoutBlocker": sum(1 for task in completed if not any(item.task_id == task.id for item in blockers)),
        "blockerCount": len(blockers),
        "selfAnalysisCompleteRate": _rate(sum(1 for item in blockers if item.self_analysis_complete), len(blockers)),
        "quizFirstPassRate": first_pass_rate,
        "averageSubmissionVersions": round(sum(versions) / len(versions), 2) if versions else None,
        "revisionRequiredCount": revision_required,
    }
    return {
        "planId": plan.id,
        "employeeId": plan.employee_id,
        "employeeCode": plan.employee_code,
        "employeeName": plan.employee_name,
        "period": plan.period,
        "generatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "objectiveSignals": {
            "completion": {
                "completed": len(completed),
                "total": len(tasks),
                "completionRate": _rate(len(completed), len(tasks)),
                "onTimeCompleted": len(on_time),
                "overdueCount": len(overdue),
            },
            "quiz": {
                "attemptBatches": len(attempts),
                "itemResults": len(quiz_rows),
                "firstPassCount": first_pass,
                "firstPassRate": independence_proxy["quizFirstPassRate"],
                "stillWrongCount": len(still_wrong),
                "wrongItems": sorted(still_wrong, key=lambda item: (-item["wrongCount"], item["knowledgeKey"]))[:20],
            },
            "submissions": {
                "count": len(submissions),
                "averageVersions": independence_proxy["averageSubmissionVersions"],
                "revisionRequiredCount": revision_required,
                "passedReviewCount": passed_reviews,
            },
            "independence": independence_proxy,
            "engagement": {
                "coursewareOpens": event_counts.get("courseware_opened", 0),
                "materialReads": event_counts.get("material_read", 0),
                "notesSaved": event_counts.get("note_saved", 0),
                "taskOpens": event_counts.get("task_opened", 0),
                "eventCounts": event_counts,
            },
            "blockers": {
                "count": len(blockers),
                "openCount": sum(1 for item in blockers if item.status in {"open", "self_processing", "pending"}),
                "types": dict(blocker_types),
            },
        },
        "capabilityEvidence": capabilities,
        "reviewHints": review_hints,
        "projectContextHints": [
            {"weekNo": week.week_no, "title": week.title, "objective": week.objective}
            for week in sorted(plan.weeks, key=lambda item: item.week_no)
        ],
        "usage": "供生成个人月度复核时引用；suggestedScore1to5 只是客观对照，不能代替 Mentor 判断。",
    }
