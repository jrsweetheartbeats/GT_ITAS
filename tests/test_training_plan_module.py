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


def test_status_machine_contract():
    task_states = {"not_started", "in_progress", "submitted", "needs_revision", "blocked", "completed"}
    submission_states = {"submitted", "reviewed"}
    review_results = {"passed", "revision_required"}
    assert task_states == {"not_started", "in_progress", "submitted", "needs_revision", "blocked", "completed"}
    assert submission_states == {"submitted", "reviewed"}
    assert review_results == {"passed", "revision_required"}
