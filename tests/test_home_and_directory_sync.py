from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

from audit_flow_system.core.security import DEFAULT_MODULE_ORDER, normalize_module_order
from audit_flow_system.services.project_directory_fields import split_project_description
from audit_flow_system.routers.projects import _ims_contact_match_filters
from audit_flow_system.models import User


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "standalone" / "sync_directory_and_projects_from_remote.py"
SPEC = importlib.util.spec_from_file_location("sync_directory_and_projects_from_remote", MODULE_PATH)
assert SPEC and SPEC.loader
sync_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_tool
SPEC.loader.exec_module(sync_tool)


class HomeModuleTests(unittest.TestCase):
    def test_module_order_pins_home_first(self) -> None:
        self.assertEqual(DEFAULT_MODULE_ORDER[0], "home")
        self.assertEqual(
            normalize_module_order(["dashboard", "projectWorkspace", "learning"]),
            ["home", "dashboard", "projectWorkspace", "learning", "qualityDashboard", "templates", "development", "config"],
        )

    def test_saved_order_without_home_still_keeps_home_first(self) -> None:
        ordered = normalize_module_order(DEFAULT_MODULE_ORDER[1:])
        self.assertEqual(ordered[0], "home")
        self.assertIn("dashboard", ordered)


class DirectorySyncHelperTests(unittest.TestCase):
    def test_realigns_local_unique_value_when_ids_differ(self) -> None:
        conn = MagicMock()
        conn.execute.return_value.mappings.return_value.all.return_value = [
            {"id": 3, "uk": "ita_lr"},
            {"id": 5, "uk": "keep"},
        ]
        changed = sync_tool.realign_unique_values(
            conn,
            "users",
            "username",
            [{"id": 5, "username": "ita_lr"}, {"id": 9, "username": "other"}],
        )
        self.assertEqual(changed, 1)
        sql = str(conn.execute.call_args_list[-1].args[0])
        self.assertIn("UPDATE", sql)
        self.assertIn("username", sql)

    def test_require_table_rejects_unknown_names(self) -> None:
        with self.assertRaises(sync_tool.SyncError):
            sync_tool.require_table("users; drop table users")


class ProjectDirectoryFieldTests(unittest.TestCase):
    def test_plain_description_stays_in_notes(self) -> None:
        fields, leftover = split_project_description("2026年1-6月半年报 IT 审计项目。")
        self.assertEqual(fields["department"], "")
        self.assertEqual(leftover, "2026年1-6月半年报 IT 审计项目。")

    def test_splits_home_fields_and_keeps_oa_metadata(self) -> None:
        fields, leftover = split_project_description(
            '{"department": "IT咨询", "charge_with_tax": "48,000.00", "oa_billid": 15311, "source": "oa"}'
        )
        self.assertEqual(fields["department"], "IT咨询")
        self.assertEqual(fields["charge_with_tax"], "48,000.00")
        self.assertIn("oa_billid", leftover)
        self.assertNotIn("department", leftover)

    def test_ims_contact_filters_use_user_emails_and_names(self) -> None:
        users = [
            User(id=1, username="a", display_name="张三", email="Ann@Firm.com", password_hash="x", role_id=1),
            User(id=2, username="b", display_name="李四", email="", password_hash="x", role_id=1),
        ]
        filters = _ims_contact_match_filters(users)
        self.assertEqual(len(filters), 2)


if __name__ == "__main__":
    unittest.main()
