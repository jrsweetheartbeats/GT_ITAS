from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "standalone" / "sync_review_findings_to_remote.py"
SPEC = importlib.util.spec_from_file_location("sync_review_findings_to_remote", MODULE_PATH)
assert SPEC and SPEC.loader
sync_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_tool
SPEC.loader.exec_module(sync_tool)


class SyncReviewFindingsTests(unittest.TestCase):
    def test_fingerprint_ignores_cosmetic_text_differences(self) -> None:
        first = {
            "c22_related": True,
            "workpaper_code": "C22",
            "issue_step": "SA-10",
            "finding_type": "ITGC",
            "issue": "密码  策略不一致",
        }
        second = {
            "c22_related": 1,
            "workpaper_code": "Ｃ２２",
            "issue_step": "sa-10",
            "finding_type": "itgc",
            "issue": " 密码\n策略不一致 ",
        }
        self.assertEqual(sync_tool.finding_fingerprint(first), sync_tool.finding_fingerprint(second))

    def test_fingerprint_is_scoped_by_workpaper_and_c22_flag(self) -> None:
        base = {"workpaper_code": "C22", "issue_step": "SA-10", "finding_type": "ITGC", "issue": "问题"}
        other_workpaper = {**base, "workpaper_code": "C21-1"}
        other_scope = {**base, "c22_related": True}
        self.assertNotEqual(sync_tool.finding_fingerprint(base), sync_tool.finding_fingerprint(other_workpaper))
        self.assertNotEqual(sync_tool.finding_fingerprint(base), sync_tool.finding_fingerprint(other_scope))

    def test_duplicate_source_findings_are_rejected(self) -> None:
        row = {
            "issue_no": "C22-001",
            "c22_related": True,
            "workpaper_code": "C22",
            "issue_step": "SA-10",
            "finding_type": "ITGC",
            "issue": "同一问题",
        }
        duplicate = {**row, "issue_no": "C22-002", "issue": "  同一问题  "}
        with self.assertRaises(sync_tool.SyncError):
            sync_tool._validate_source_rows([row, duplicate])

    def test_only_mariadb_urls_are_accepted(self) -> None:
        accepted = "mariadb+pymysql://user:pass@localhost/ITAS"
        self.assertEqual(sync_tool.require_mariadb_url(accepted, "DB_URL"), accepted)
        with self.assertRaises(sync_tool.SyncError):
            sync_tool.require_mariadb_url("sqlite:///tmp/test.db", "DB_URL")

    def test_insert_statement_uses_insert_ignore(self) -> None:
        self.assertIn("INSERT IGNORE INTO review_findings", str(sync_tool.INSERT_FINDING_SQL))


if __name__ == "__main__":
    unittest.main()
