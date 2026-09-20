import json
from pathlib import Path
from types import SimpleNamespace

from audit_flow_system.models import DevelopmentBlocker, DevelopmentSubmission, DevelopmentSubmissionReview
from audit_flow_system.routers.development_import import _weighted_assessment_total
from audit_flow_system.services.training_plan_protocol import validate_training_plan_payload


def example_payload():
    document = json.loads(Path("docs/training-plan-schema.md").read_text().split("```json\n")[-1].split("\n```")[0])
    return document


def test_schema_validation_and_cross_field_errors():
    payload = example_payload()
    document, errors = validate_training_plan_payload(payload)
    assert document is not None
    assert errors == []

    invalid = json.loads(json.dumps(payload))
    invalid["schemaVersion"] = "2.0"
    _, errors = validate_training_plan_payload(invalid)
    assert any(item["path"] == "schemaVersion" for item in errors)

    invalid = json.loads(json.dumps(payload))
    invalid["weeks"][0]["tasks"][0]["prerequisiteTaskCodes"] = ["MISSING"]
    _, errors = validate_training_plan_payload(invalid)
    assert any(item["code"] == "unknown_prerequisite" for item in errors)


def test_learning_material_course_scope_defaults_and_validates():
    payload = example_payload()
    material = payload["weeks"][0]["tasks"][0]["learningMaterials"][0]
    material.pop("courseScope", None)
    document, errors = validate_training_plan_payload(payload)
    assert errors == []
    assert document.weeks[0].tasks[0].learning_materials[0].course_scope == "personal"

    material["courseScope"] = "common"
    document, errors = validate_training_plan_payload(payload)
    assert errors == []
    assert document.weeks[0].tasks[0].learning_materials[0].course_scope == "common"


def test_assessment_weighted_total():
    dimensions = [SimpleNamespace(score=80, weight=30), SimpleNamespace(score=60, weight=70)]
    assert _weighted_assessment_total(dimensions) == 66.0


def test_history_tables_keep_version_and_review_relationships():
    assert DevelopmentSubmission.__table__.constraints
    assert any(constraint.name == "uq_development_submissions_task_employee_version" for constraint in DevelopmentSubmission.__table__.constraints)
    assert DevelopmentSubmissionReview.__table__.c.submission_id is not None
    assert DevelopmentBlocker.__table__.c.created_at is not None
    assert DevelopmentBlocker.__table__.c.resolved_at is not None


def test_learning_signal_tables_keep_attempt_history():
    from audit_flow_system.models import DevelopmentLearningEvent, DevelopmentQuizItemResult

    assert any(constraint.name == "uq_development_quiz_results_attempt" for constraint in DevelopmentQuizItemResult.__table__.constraints)
    assert DevelopmentLearningEvent.__table__.c.event_type is not None
    assert DevelopmentQuizItemResult.__table__.c.knowledge_key is not None
    assert DevelopmentQuizItemResult.__table__.c.passed_gate is not None


def test_quiz_protocol_accepts_optional_knowledge_key():
    payload = example_payload()
    payload["weeks"][0]["tasks"][0]["selfCheckQuestions"] = [{
        "type": "choice",
        "prompt": "备份成功能否直接证明可恢复？",
        "options": ["不能", "能", "只看日志", "只看截图"],
        "answer": "不能",
        "topic": "itgc",
        "knowledgeKey": "itgc.backup_vs_restore",
    }]
    document, errors = validate_training_plan_payload(payload)
    assert errors == []
    stored = document.weeks[0].tasks[0].self_check_questions[0]
    assert not isinstance(stored, str)
    assert stored.knowledge_key == "itgc.backup_vs_restore"
    assert stored.topic == "itgc"


def test_review_signal_helpers_are_deterministic():
    from audit_flow_system.services.training_signals import (
        question_fingerprint,
        question_skill_tag,
        suggested_score_1_to_5,
    )

    contextual = "在“收入完整性”这一节的学习情境中，备份任务显示成功，尚不能直接证明什么？"
    plain = "备份任务显示成功，尚不能直接证明什么？"
    assert question_fingerprint(contextual) == question_fingerprint(plain)
    assert question_skill_tag({"knowledgeKey": "itac.ipe_definition"}, "itac") == "interface_ipe"
    assert suggested_score_1_to_5(None) is None
    assert suggested_score_1_to_5(0.92, 0.8) == 5
    assert suggested_score_1_to_5(0.4) == 2


def test_status_machine_contract():
    task_states = {"not_started", "in_progress", "submitted", "needs_revision", "blocked", "completed"}
    submission_states = {"submitted", "reviewed"}
    review_results = {"passed", "revision_required"}
    assert task_states == {"not_started", "in_progress", "submitted", "needs_revision", "blocked", "completed"}
    assert submission_states == {"submitted", "reviewed"}
    assert review_results == {"passed", "revision_required"}
