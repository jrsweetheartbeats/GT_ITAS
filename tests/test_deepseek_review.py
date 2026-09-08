from types import SimpleNamespace
import unittest

from audit_flow_system.schemas import ReviewRunIn
from audit_flow_system.services.deepseek_review import (
    DeepSeekReviewError,
    _extract_response_text,
    _parse_json_object,
    _review_instructions,
    _validate_findings,
)


class DeepSeekReviewTests(unittest.TestCase):
    def test_review_engine_is_versioned_without_breaking_old_payload(self) -> None:
        self.assertEqual(ReviewRunIn(project_id=1).review_engine, "rules")
        self.assertEqual(ReviewRunIn(project_id=1, review_engine="deepseek").review_engine, "deepseek")

    def test_extracts_chat_completion_content(self) -> None:
        payload = {"choices": [{"message": {"content": '{"summary":"ok","findings":[]}'}}]}
        self.assertEqual(_extract_response_text(payload), '{"summary":"ok","findings":[]}')

    def test_parses_json_inside_markdown_fence(self) -> None:
        payload = _parse_json_object('```json\n{"summary":"ok","findings":[]}\n```')
        self.assertEqual(payload["summary"], "ok")

    def test_rejects_findings_without_known_workpaper_or_evidence(self) -> None:
        known = {"c21": SimpleNamespace(code="C21")}
        payload = {
            "findings": [
                {
                    "workpaperCode": "C21",
                    "ruleCode": "AI-001",
                    "severity": "high",
                    "location": "Sheet1!A1",
                    "issue": "未记录复核结论",
                    "evidence": "结论栏为空",
                    "recommendation": "补充结论",
                },
                {"workpaperCode": "UNKNOWN", "issue": "未知底稿", "evidence": "无"},
                {"workpaperCode": "C21", "issue": "缺少证据", "evidence": ""},
            ]
        }
        findings, rejected = _validate_findings(payload, known)
        self.assertEqual(len(findings), 1)
        self.assertEqual(rejected, 2)
        self.assertEqual(findings[0]["target"], "C21 Sheet1!A1")

    def test_non_json_model_response_is_rejected(self) -> None:
        with self.assertRaises(DeepSeekReviewError):
            _parse_json_object("没有结构化结果")

    def test_review_instructions_load_current_rule_library(self) -> None:
        instructions = _review_instructions()
        self.assertIn("EXEC-007", instructions)
        self.assertIn("应传条数", instructions)
        self.assertIn("当前复核规则", instructions)


if __name__ == "__main__":
    unittest.main()
