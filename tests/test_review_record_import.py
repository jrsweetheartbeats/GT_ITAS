from io import BytesIO
import unittest

from openpyxl import Workbook

from audit_flow_system.routers.reviews import _finding_change_text, _next_review_stage_from_rows, _parse_import_rows
from audit_flow_system.services.review_catalog import filter_review_issue_catalog, review_issue_catalog


class ReviewRecordImportTests(unittest.TestCase):
    def test_full_review_record_sheet_maps_workbook_fields(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "问题汇总"
        sheet.append([
            "序号", "阶段", "问题类型（例如：ITGC、ITAC等）", "复核问题", "具体描述补充", "问题步骤归属",
            "问题类别", "对应文件名", "问题出现的复核阶段", "项目组回复", "确认复核问题已满意解决",
            "公司", "C22与否类型", "现场负责人", "项目组内复核人", "备注", "", "", "", "", "是否高风险",
        ])
        sheet.append([
            1, "执行阶段", "ITGC", "测试问题", "测试证据", "E1", "审计证据缺失或不全", "C22 ITGC-SA-3",
            "第一轮", "已补充", "是", "测试公司", "C22", "现场经理", "项目复核人", "备注", "", "", "", "", "是",
        ])
        buffer = BytesIO()
        workbook.save(buffer)

        rows, errors = _parse_import_rows(buffer.getvalue())

        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["c22_related"])
        self.assertTrue(row["resolution_confirmed"])
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["issue_step"], "E1")
        self.assertEqual(row["project_reply"], "已补充")
        self.assertEqual(row["field_lead"], "现场经理")
        self.assertEqual(row["project_reviewer"], "项目复核人")

    def test_catalog_contains_both_review_scopes(self) -> None:
        rows = review_issue_catalog()
        self.assertEqual(len(rows), 623)
        self.assertTrue(filter_review_issue_catalog(scope="C22", keyword="操作系统", limit=5))
        self.assertTrue(filter_review_issue_catalog(scope="非C22", keyword="索引", limit=5))

    def test_review_stage_advances_only_after_all_current_findings_close(self) -> None:
        self.assertEqual(_next_review_stage_from_rows([]), "第一阶段")
        self.assertEqual(
            _next_review_stage_from_rows([("第一阶段", "closed"), ("第一阶段", "open")]),
            "第一阶段",
        )
        self.assertEqual(
            _next_review_stage_from_rows([("第一阶段", "closed"), ("第一阶段", "resolved")]),
            "第二阶段",
        )
        self.assertEqual(
            _next_review_stage_from_rows([("第一阶段", "closed"), ("第二阶段", "changes_requested")]),
            "第二阶段",
        )

    def test_finding_change_log_records_field_and_before_after_values(self) -> None:
        self.assertEqual(_finding_change_text("issue", "原问题", "修改后问题"), "复核问题：原问题 -> 修改后问题")
        self.assertEqual(_finding_change_text("resolution_confirmed", False, True), "确认满意解决：否 -> 是")


if __name__ == "__main__":
    unittest.main()
