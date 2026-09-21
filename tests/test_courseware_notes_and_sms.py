from __future__ import annotations

import unittest
from types import SimpleNamespace

from audit_flow_system.services.courseware_notes import chapter_payload, group_notes_by_module
from audit_flow_system.services.mail import mask_email, normalize_email


class CoursewareNoteHelperTests(unittest.TestCase):
    def test_groups_empty_notes_by_module(self) -> None:
        notes = chapter_payload([])
        grouped = group_notes_by_module(notes)
        self.assertEqual(len(notes), 6)
        self.assertEqual([item["module"] for item in grouped], ["定位与目标", "核心概念", "程序与证据", "任务推演", "风险实质", "完成标准"])
        self.assertTrue(all(item["content"] == "" for item in notes))

    def test_keeps_saved_chapter_content(self) -> None:
        row = SimpleNamespace(chapter_key="risk", content="控制失效会传导到报表", updated_at=None)
        notes = chapter_payload([row])
        by_key = {item["key"]: item for item in notes}
        self.assertEqual(by_key["risk"]["content"], "控制失效会传导到报表")
        self.assertEqual(by_key["orientation"]["content"], "")


class MailHelperTests(unittest.TestCase):
    def test_masks_email_local_part(self) -> None:
        self.assertEqual(normalize_email("  lirui5@cn.gt.com  "), "lirui5@cn.gt.com")
        self.assertEqual(mask_email("lirui5@cn.gt.com"), "li***@cn.gt.com")
        self.assertEqual(mask_email("ab@cn.gt.com"), "a*@cn.gt.com")


if __name__ == "__main__":
    unittest.main()
