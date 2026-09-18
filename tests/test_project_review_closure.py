from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from datetime import datetime, timedelta

from fastapi import HTTPException

from audit_flow_system.core.security import project_reviewer_ids
from audit_flow_system.app import app
from audit_flow_system.models import ReviewFinding, ReviewFindingResponse, ReviewStep, ReviewStepHistory, Workpaper, WorkpaperVersion
from audit_flow_system.routers.reviews import (
    _ensure_step_actor,
    _assignments_from_selected_reviewer,
    _project_review_assignments,
    _validate_resubmission_version,
    respond_to_review_finding,
    update_review_finding,
)
from audit_flow_system.routers.workpapers import _ensure_existing_upload_allowed, _uploaded_workpaper_status
from audit_flow_system.schemas import ReviewFindingIn, ReviewFindingPatchIn, ReviewFindingResponseIn
from audit_flow_system.services.timeliness import is_open_like
from audit_flow_system.routers.workflow import _workpaper_done
from audit_flow_system.services.bootstrap import DEFAULT_ROLE_PERMISSIONS


def user(user_id: int, role_code: str = "preparer") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=SimpleNamespace(code=role_code))


class ProjectReviewClosureTests(unittest.TestCase):
    def test_manual_finding_schema_accepts_optional_assignee(self) -> None:
        body = ReviewFindingIn(project_id=1, issue="密码策略结论不一致", assignee_user_id=2)
        self.assertEqual(body.assignee_user_id, 2)

    def test_project_review_assignments_follow_configured_people(self) -> None:
        project = SimpleNamespace(
            project_leader_user_id=11,
            manager_user_id=12,
            director_user_id=13,
            partner_user_id=14,
            quality_reviewer_user_id=None,
        )
        self.assertEqual(
            _project_review_assignments(project),
            [
                ("project_manager", 11),
                ("responsible_manager", 12),
                ("director", 13),
                ("partner", 14),
            ],
        )
        self.assertEqual(project_reviewer_ids(project), {11, 12, 13, 14})

    def test_selected_next_reviewer_starts_at_that_configured_level(self) -> None:
        project = SimpleNamespace(
            project_leader_user_id=11,
            manager_user_id=12,
            director_user_id=13,
            partner_user_id=14,
            quality_reviewer_user_id=None,
        )
        self.assertEqual(
            _assignments_from_selected_reviewer(project, 12),
            [("responsible_manager", 12), ("director", 13), ("partner", 14)],
        )
        with self.assertRaises(HTTPException) as unconfigured:
            _assignments_from_selected_reviewer(project, 99)
        self.assertEqual(unconfigured.exception.status_code, 400)

    def test_only_pending_assigned_reviewer_can_decide(self) -> None:
        step = SimpleNamespace(reviewer_user_id=11, status="pending")
        _ensure_step_actor(step, user(11))
        with self.assertRaises(HTTPException) as wrong_user:
            _ensure_step_actor(step, user(12))
        self.assertEqual(wrong_user.exception.status_code, 403)
        step.status = "approved"
        with self.assertRaises(HTTPException) as repeated:
            _ensure_step_actor(step, user(11))
        self.assertEqual(repeated.exception.status_code, 409)

    def test_submitted_workpaper_is_not_complete(self) -> None:
        self.assertFalse(_workpaper_done("submitted"))
        self.assertFalse(_workpaper_done("returned"))
        self.assertTrue(_workpaper_done("approved"))

    def test_history_models_are_append_only_entities(self) -> None:
        self.assertIn("uq_workpaper_versions_workpaper_version", {item.name for item in WorkpaperVersion.__table__.constraints})
        self.assertIn("uq_review_finding_responses_finding_round", {item.name for item in ReviewFindingResponse.__table__.constraints})
        self.assertIsNotNone(ReviewStepHistory.__table__.c.step_id)

    def test_finding_update_does_not_read_response_only_field(self) -> None:
        db = MagicMock()
        db.execute.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as missing:
            update_review_finding(1, ReviewFindingPatchIn(issue="补充问题描述"), db, user(1, "admin"))
        self.assertEqual(missing.exception.status_code, 404)

    def test_finding_response_uses_trimmed_body_text(self) -> None:
        db = MagicMock()
        db.execute.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as missing:
            respond_to_review_finding(1, ReviewFindingResponseIn(response_text="已上传修订版本"), db, user(1))
        self.assertEqual(missing.exception.status_code, 404)
        with self.assertRaises(HTTPException) as blank:
            respond_to_review_finding(1, ReviewFindingResponseIn(response_text="   "), db, user(1))
        self.assertEqual(blank.exception.status_code, 400)

    def test_returned_upload_preserves_explicit_resubmission_state(self) -> None:
        self.assertEqual(_uploaded_workpaper_status("returned"), "returned")
        self.assertEqual(_uploaded_workpaper_status("draft"), "draft")

    def test_project_member_can_take_over_draft_or_returned_workpaper_but_not_in_review(self) -> None:
        project = SimpleNamespace(
            creator_user_id=10,
            project_leader_user_id=11,
            manager_user_id=12,
        )
        member = user(20)
        someone_elses = SimpleNamespace(preparer_user_id=21, status="draft")
        _ensure_existing_upload_allowed(someone_elses, project, member, 20)
        own_in_review = SimpleNamespace(preparer_user_id=20, status="submitted")
        with self.assertRaises(HTTPException) as overwrite:
            _ensure_existing_upload_allowed(own_in_review, project, member, 20)
        self.assertEqual(overwrite.exception.status_code, 409)
        own_returned = SimpleNamespace(preparer_user_id=20, status="returned")
        _ensure_existing_upload_allowed(own_returned, project, member, 20)

    def test_project_member_can_claim_an_unedited_standard_template(self) -> None:
        project = SimpleNamespace(
            creator_user_id=10,
            project_leader_user_id=11,
            manager_user_id=12,
        )
        template = SimpleNamespace(
            preparer_user_id=11,
            status="draft",
            extracted_fields_json='{"workspace_initialized": true}',
        )
        _ensure_existing_upload_allowed(template, project, user(20), 20)

    def test_resubmission_requires_a_different_workpaper_version(self) -> None:
        now = datetime.utcnow()
        rejected = SimpleNamespace(workpaper_version_id=7, reviewed_at=now)
        same_version = SimpleNamespace(id=7, created_at=now - timedelta(minutes=1))
        with self.assertRaises(HTTPException) as unchanged:
            _validate_resubmission_version(rejected, same_version)
        self.assertEqual(unchanged.exception.status_code, 409)
        new_version = SimpleNamespace(id=8, created_at=now + timedelta(minutes=1))
        _validate_resubmission_version(rejected, new_version)

    def test_review_entities_bind_to_the_reviewed_version(self) -> None:
        self.assertIsNotNone(ReviewStep.__table__.c.workpaper_version_id)
        self.assertIsNotNone(ReviewStepHistory.__table__.c.workpaper_version_id)
        self.assertIsNotNone(ReviewFinding.__table__.c.workpaper_id)
        self.assertIsNotNone(ReviewFinding.__table__.c.resolved_workpaper_version_id)
        self.assertIsNotNone(ReviewFinding.__table__.c.review_step_id)
        self.assertIn("uq_workpapers_project_code", {item.name for item in Workpaper.__table__.constraints})

    def test_changes_requested_remains_open_for_overdue_tracking(self) -> None:
        self.assertTrue(is_open_like("changes_requested"))
        self.assertFalse(is_open_like("responded"))
        self.assertFalse(is_open_like("closed"))

    def test_project_review_queue_route_is_registered(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertIn("/api/projects/{project_id}/review-steps", paths)
        self.assertIn("/api/projects/{project_id}/reviewer-options", paths)
        self.assertIn("/api/workpapers/batch-submit", paths)
        self.assertIn("/api/workpapers/{workpaper_id}/download", paths)
        self.assertIn("/api/workpapers/{workpaper_id}/open-local", paths)

    def test_manager_and_above_can_open_workpaper_review_ui(self) -> None:
        for role_code in ["manager", "senior_manager", "director", "partner", "quality"]:
            with self.subTest(role_code=role_code):
                self.assertIn("reviewCenter", DEFAULT_ROLE_PERMISSIONS[role_code]["view"])
                self.assertIn("workpapers", DEFAULT_ROLE_PERMISSIONS[role_code]["view"])


if __name__ == "__main__":
    unittest.main()
