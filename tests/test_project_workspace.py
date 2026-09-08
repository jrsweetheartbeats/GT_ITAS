from pathlib import Path
from types import SimpleNamespace
import unittest

from audit_flow_system.services.projects import (
    DEFAULT_TEMPLATE_FILES,
    PROJECT_FOLDER_STRUCTURE,
    TEMPLATE_ROOT,
    default_project_root,
    public_workspace_report,
)
from audit_flow_system.services.materials import safe_relative_upload_path, workpaper_upload_root
from audit_flow_system.services.workpaper_catalog import validate_workpaper_index_code
from audit_flow_system.services.workpaper_reader import build_workpaper_tree
from audit_flow_system.routers.workpapers import _attachment_index_prefix_from_path, _non_basic_workpaper_code_from_path


class ProjectWorkspaceTests(unittest.TestCase):
    def test_default_root_uses_safe_project_identity(self) -> None:
        project = SimpleNamespace(
            id=17,
            audit_year=2026,
            entity_name='测试/公司:*?"<>|',
            name="测试项目",
            code="IT/2026",
        )
        root = default_project_root(project, Path("/tmp/itas-projects"))
        self.assertEqual(root.parent, Path("/tmp/itas-projects"))
        self.assertEqual(root.name, "2026_测试_公司_IT_2026_P17")

    def test_bundled_default_templates_are_complete(self) -> None:
        self.assertEqual(len(DEFAULT_TEMPLATE_FILES), 15)
        self.assertFalse(
            [spec["code"] for spec in DEFAULT_TEMPLATE_FILES if not (TEMPLATE_ROOT / spec["source"]).is_file()]
        )
        self.assertEqual(len({spec["code"] for spec in DEFAULT_TEMPLATE_FILES}), len(DEFAULT_TEMPLATE_FILES))
        self.assertEqual(DEFAULT_TEMPLATE_FILES[0]["code"], "B22A-4")

    def test_workspace_has_basic_workpaper_structure(self) -> None:
        self.assertIn(Path("底稿") / "计划阶段", PROJECT_FOLDER_STRUCTURE)
        self.assertIn(Path("底稿") / "执行阶段", PROJECT_FOLDER_STRUCTURE)
        self.assertIn(Path("底稿") / "结束阶段", PROJECT_FOLDER_STRUCTURE)
        self.assertIn(Path("资料管理"), PROJECT_FOLDER_STRUCTURE)
        self.assertIn(Path("复核记录"), PROJECT_FOLDER_STRUCTURE)

    def test_internal_rollback_paths_are_not_returned_to_api(self) -> None:
        report = public_workspace_report(
            {
                "workpapers_created": 15,
                "_created_files": ["/tmp/a.xlsx"],
                "_created_directories": ["/tmp/project"],
            }
        )
        self.assertEqual(report, {"workpapers_created": 15})

    def test_empty_project_tree_does_not_show_unuploaded_basic_workpapers(self) -> None:
        tree = build_workpaper_tree([])
        self.assertEqual([stage["stage"] for stage in tree], ["planning", "execution", "delivery", "reporting"])
        self.assertTrue(all(not stage["children"] for stage in tree))

    def test_c22_test_point_is_nested_below_c22_not_a_workpaper_root(self) -> None:
        legacy = SimpleNamespace(
            id=9,
            code="C22.SA-5",
            name="新增用户测试",
            stage="execution",
            status="draft",
            file_path="/tmp/C22.SA-5.xlsx",
        )
        tree = build_workpaper_tree([legacy])
        execution = next(stage for stage in tree if stage["stage"] == "execution")
        self.assertNotIn("C22.SA-5", [child.get("code") for child in execution["children"]])
        folder = next(child for child in execution["children"] if child["type"] == "test_point_folder")
        self.assertEqual(folder["children"][0]["type"], "test_point")
        self.assertTrue(folder["children"][0]["label"].startswith("SA-5 "))

    def test_test_point_cannot_be_used_as_workpaper_index(self) -> None:
        self.assertEqual(validate_workpaper_index_code(" c22 "), "C22")
        for value in ("SA-5", "C22.SA-5", "c22-sa-5-1", "PM-4e"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "C22.*测试点"):
                validate_workpaper_index_code(value)

    def test_upload_root_follows_selected_tree_stage(self) -> None:
        project = SimpleNamespace(id=3, project_root="/tmp/itas-project")
        self.assertEqual(workpaper_upload_root(project, "planning"), Path("/tmp/itas-project/底稿/计划阶段"))
        self.assertEqual(workpaper_upload_root(project, "execution"), Path("/tmp/itas-project/底稿/执行阶段"))
        self.assertEqual(workpaper_upload_root(project, "delivery"), Path("/tmp/itas-project/底稿/结束阶段"))

    def test_batch_import_relative_path_keeps_folders_and_drops_traversal(self) -> None:
        self.assertEqual(
            safe_relative_upload_path("客户项目/C22资料/用户清单.xlsx", "用户清单.xlsx"),
            Path("客户项目/C22资料/用户清单.xlsx"),
        )
        self.assertEqual(
            safe_relative_upload_path("../../客户项目/../C22.xlsx", "C22.xlsx"),
            Path("客户项目/C22.xlsx"),
        )

    def test_batch_import_files_are_rendered_as_folder_tree(self) -> None:
        attachment = SimpleNamespace(
            id=8,
            workpaper_id=None,
            index_no="P-1",
            title="用户清单",
            file_type="xlsx",
            status="active",
            file_path="/tmp/itas-project/资料管理/批量导入/客户项目/C22资料/用户清单.xlsx",
            referenced_in="",
        )
        tree = build_workpaper_tree([], [attachment], "/tmp/itas-project")
        execution = next(stage for stage in tree if stage["stage"] == "execution")
        loose = next(child for child in execution["children"] if child["type"] == "attachment_folder")
        batch = next(child for child in loose["children"] if child["type"] == "attachment_path_folder")
        self.assertEqual(batch["label"], "批量导入文件")
        self.assertEqual(batch["children"][0]["label"], "客户项目")

    def test_batch_import_recognizes_non_basic_workpaper_and_attachment_indexes(self) -> None:
        self.assertEqual(_non_basic_workpaper_code_from_path("导入/A14-3 IT审计备忘录.docx"), "A14-3")
        self.assertEqual(_non_basic_workpaper_code_from_path("导入/C22附件/测试底稿.xlsx"), "C22")
        self.assertEqual(_non_basic_workpaper_code_from_path("导入/C22.SA-5/用户清单.xlsx"), "")
        self.assertEqual(_attachment_index_prefix_from_path("导入/C22.SA-5/用户清单.xlsx"), "SA-5")
        self.assertEqual(_attachment_index_prefix_from_path("导入/SA-5-2 E3系统/用户清单.xlsx"), "SA-5-2")


if __name__ == "__main__":
    unittest.main()
