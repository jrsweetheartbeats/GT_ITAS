"""Stable ChatGPT -> ITAS training-plan JSON protocol (schemaVersion 1.0)."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError


SCHEMA_VERSION = "1.0"
WEEK_DATE_SLACK_DAYS = 7


class ProtocolModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        loc_by_alias=True,
    )


class ProtocolEmployee(ProtocolModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)


class ProtocolPlan(ProtocolModel):
    title: str = Field(min_length=1, max_length=240)
    plan_type: str = Field(alias="type", min_length=1, max_length=80)
    period: str = Field(min_length=1, max_length=80)
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    overall_goal: str = Field(alias="overallGoal")
    mentor_code: str = Field(alias="mentorCode")


class ProtocolLearningMaterial(ProtocolModel):
    title: str = Field(min_length=1, max_length=240)
    material_type: Literal["itas_page", "external_link", "document", "video", "case", "reference"] = Field(alias="type")
    course_scope: Literal["common", "personal"] = Field(default="personal", alias="courseScope")
    url: str
    description: str


class ProtocolSubmissionSpec(ProtocolModel):
    required: bool
    submission_type: str = Field(alias="submissionType")
    title: str
    requirements: str


class ProtocolQuizQuestion(ProtocolModel):
    type: Literal["choice", "fill_blank"]
    prompt: str = Field(min_length=1, max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=20)
    answer: Union[str, list[str]]
    topic: str = Field(default="", max_length=40)
    knowledge_key: str = Field(default="", alias="knowledgeKey", max_length=80)


class ProtocolTask(ProtocolModel):
    task_code: str = Field(alias="taskCode", min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=240)
    task_type: Literal["learning", "quiz", "practice", "project", "assignment", "self_check", "review"] = Field(alias="taskType")
    description: str
    purpose: str = ""
    start_date: date = Field(alias="startDate")
    due_date: date = Field(alias="dueDate")
    estimated_hours: float = Field(alias="estimatedHours", ge=0)
    prerequisite_task_codes: list[str] = Field(alias="prerequisiteTaskCodes")
    learning_materials: list[ProtocolLearningMaterial] = Field(alias="learningMaterials")
    instructions: str
    submission: ProtocolSubmissionSpec
    completion_criteria: str = Field(alias="completionCriteria")
    self_check_questions: list[Union[str, ProtocolQuizQuestion]] = Field(default_factory=list, alias="selfCheckQuestions")
    mentor_review_required: bool = Field(alias="mentorReviewRequired")


class ProtocolWeek(ProtocolModel):
    week_no: int = Field(alias="weekNo", ge=1)
    title: str = Field(min_length=1, max_length=240)
    objective: str
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    expected_deliverable: str = Field(alias="expectedDeliverable")
    tasks: list[ProtocolTask] = Field(min_length=1)


class ProtocolAssessmentDimension(ProtocolModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    weight: float = Field(gt=0)
    description: str


class ProtocolThreshold(ProtocolModel):
    min_score: float = Field(alias="min", ge=0, le=100)
    max_score: float = Field(alias="max", ge=0, le=100)
    next_action: str = Field(alias="nextAction", min_length=1, max_length=120)


class ProtocolAssessment(ProtocolModel):
    dimensions: list[ProtocolAssessmentDimension] = Field(min_length=1)
    total_score: float = Field(alias="totalScore", gt=0)
    thresholds: list[ProtocolThreshold] = Field(min_length=1)


class TrainingPlanDocument(ProtocolModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    employee: ProtocolEmployee
    plan: ProtocolPlan
    weeks: list[ProtocolWeek] = Field(min_length=1)
    assessment: ProtocolAssessment


def _path(loc: tuple[Any, ...]) -> str:
    result = ""
    for part in loc:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += ("." if result else "") + str(part)
    return result or "$"


def _error(path: str, message: str, code: str = "value_error") -> dict[str, str]:
    return {"path": path, "message": message, "code": code}


def _cross_validate(document: TrainingPlanDocument) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    plan_start = document.plan.start_date
    plan_end = document.plan.end_date
    if plan_start > plan_end:
        errors.append(_error("plan.startDate", "培养计划开始日期不能晚于结束日期", "date_order"))

    week_numbers: dict[int, int] = {}
    task_codes: dict[str, tuple[int, int]] = {}
    for week_index, week in enumerate(document.weeks):
        if week.week_no in week_numbers:
            errors.append(_error(f"weeks[{week_index}].weekNo", f"weekNo {week.week_no} 在同一计划内重复", "duplicate_week_no"))
        else:
            week_numbers[week.week_no] = week_index
        if week.start_date > week.end_date:
            errors.append(_error(f"weeks[{week_index}].startDate", "培养周开始日期不能晚于结束日期", "date_order"))
        if week.start_date < plan_start.fromordinal(plan_start.toordinal() - WEEK_DATE_SLACK_DAYS) or week.end_date > plan_end.fromordinal(plan_end.toordinal() + WEEK_DATE_SLACK_DAYS):
            errors.append(_error(f"weeks[{week_index}]", "培养周日期明显超出培养计划周期", "week_outside_plan"))
        for task_index, task in enumerate(week.tasks):
            code = task.task_code
            if code in task_codes:
                errors.append(_error(f"weeks[{week_index}].tasks[{task_index}].taskCode", f"taskCode {code} 在同一计划内重复", "duplicate_task_code"))
            else:
                task_codes[code] = (week_index, task_index)
            if task.start_date > task.due_date:
                errors.append(_error(f"weeks[{week_index}].tasks[{task_index}].startDate", "任务开始日期不能晚于截止日期", "date_order"))
            if task.start_date < week.start_date or task.due_date > week.end_date:
                errors.append(_error(f"weeks[{week_index}].tasks[{task_index}]", "任务日期必须位于所属培养周范围内", "task_outside_week"))
            for question_index, question in enumerate(task.self_check_questions):
                if isinstance(question, ProtocolQuizQuestion):
                    if question.type == "choice" and len(question.options) < 2:
                        errors.append(_error(f"weeks[{week_index}].tasks[{task_index}].selfCheckQuestions[{question_index}]", "选择题至少需要两个选项", "quiz_options"))
                    expected = question.answer if isinstance(question.answer, list) else [question.answer]
                    if question.type == "choice" and any(str(answer) not in question.options for answer in expected):
                        errors.append(_error(f"weeks[{week_index}].tasks[{task_index}].selfCheckQuestions[{question_index}].answer", "选择题标准答案必须来自 options", "quiz_answer"))

    for week_index, week in enumerate(document.weeks):
        for task_index, task in enumerate(week.tasks):
            for prerequisite in task.prerequisite_task_codes:
                if prerequisite not in task_codes:
                    errors.append(_error(f"weeks[{week_index}].tasks[{task_index}].prerequisiteTaskCodes", f"前置任务 {prerequisite} 不存在", "unknown_prerequisite"))
                elif prerequisite == task.task_code:
                    errors.append(_error(f"weeks[{week_index}].tasks[{task_index}].prerequisiteTaskCodes", "任务不能依赖自身", "self_prerequisite"))

    dimensions = document.assessment.dimensions
    dimension_codes: set[str] = set()
    weight_total = 0.0
    for index, dimension in enumerate(dimensions):
        if dimension.code in dimension_codes:
            errors.append(_error(f"assessment.dimensions[{index}].code", f"评分维度 code {dimension.code} 重复", "duplicate_dimension_code"))
        dimension_codes.add(dimension.code)
        weight_total += dimension.weight
    if abs(weight_total - 100.0) > 0.01:
        errors.append(_error("assessment.dimensions", f"评分权重合计必须为100，当前为{weight_total:g}", "weight_total"))
    if abs(document.assessment.total_score - 100.0) > 0.01:
        errors.append(_error("assessment.totalScore", "当前协议要求 totalScore 为100", "total_score"))

    previous_max: Optional[float] = None
    for index, threshold in enumerate(sorted(document.assessment.thresholds, key=lambda item: item.min_score)):
        if threshold.min_score > threshold.max_score:
            errors.append(_error(f"assessment.thresholds[{index}]", "阈值 min 不能大于 max", "threshold_order"))
        if previous_max is not None and threshold.min_score <= previous_max:
            errors.append(_error(f"assessment.thresholds[{index}]", "评分阈值不能重叠", "threshold_overlap"))
        previous_max = threshold.max_score
    return errors


def validate_training_plan_payload(payload: Any) -> tuple[Optional[TrainingPlanDocument], list[dict[str, str]]]:
    if not isinstance(payload, dict):
        return None, [_error("$", "请求体必须是 JSON 对象", "type_error")]
    try:
        document = TrainingPlanDocument.model_validate(payload)
    except ValidationError as exc:
        errors = []
        for item in exc.errors():
            errors.append(_error(_path(tuple(item.get("loc", ()))), str(item.get("msg", "字段值无效")), str(item.get("type", "value_error"))))
        return None, errors
    return document, _cross_validate(document)


def training_plan_json(document: TrainingPlanDocument) -> dict[str, Any]:
    return document.model_dump(by_alias=True, mode="json")
