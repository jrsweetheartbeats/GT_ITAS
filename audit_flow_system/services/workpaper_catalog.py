from __future__ import annotations

import re
from typing import Any


# 这里是“基础底稿”的唯一目录。code 是底稿文件名前的索引号，
# SA-5 / PE-5 / PM-4e 等只是 C22 底稿内的测试点，不得作为独立底稿编号。
BASIC_WORKPAPER_SPECS: list[dict[str, str]] = [
    {"code": "B22A-4", "name": "了解企业层面控制 - 信息与沟通", "stage": "planning", "source": "计划阶段/B22A-4 了解企业层面控制 - 信息与沟通.xlsx"},
    {"code": "B22A-4-1", "name": "IT概要", "stage": "planning", "source": "计划阶段/B22A-4-1 IT概要.xlsx"},
    {"code": "B22A-4-2", "name": "重大业务流程涉及的信息系统", "stage": "planning", "source": "计划阶段/B22A-4-2 重大业务流程涉及的信息系统.xlsx"},
    {"code": "B22A-4-3", "name": "了解IT环境", "stage": "planning", "source": "计划阶段/B22A-4-3 了解IT环境.xlsm"},
    {"code": "B22A-4-4-1", "name": "了解IT一般控制", "stage": "planning", "source": "计划阶段/B22A-4-4-1 了解IT一般控制.xlsx"},
    {"code": "B22A-4-4-2", "name": "IT一般控制职责分离分析", "stage": "planning", "source": "计划阶段/B22A-4-4-2 IT一般控制职责分离分析.xlsx"},
    {"code": "B23-15", "name": "了解信息处理控制", "stage": "planning", "source": "计划阶段/B23-15 了解信息处理控制.xlsx"},
    {"code": "B60-2-1", "name": "IT复杂性判断表", "stage": "planning", "source": "计划阶段/B60-2-1 IT复杂性判断表.docx"},
    {"code": "B60-2-2", "name": "IT审计进场前通知表", "stage": "planning", "source": "计划阶段/B60-2-2 IT审计进场前通知表.docx"},
    {"code": "B60-2-3", "name": "IT审计计划备忘录", "stage": "planning", "source": "计划阶段/B60-2-3 IT审计计划备忘录.docx"},
    {"code": "C22", "name": "IT一般控制测试", "stage": "execution", "source": "执行阶段/C22 IT一般控制测试.xlsx"},
    {"code": "C26", "name": "信息处理控制测试", "stage": "execution", "source": "执行阶段/C26 信息处理控制测试.xlsx"},
    {"code": "C21", "name": "具有信息技术专业技能的项目组成员", "stage": "delivery", "source": "结束阶段/C21 具有信息技术专业技能的项目组成员.xlsx"},
    {"code": "C21-1", "name": "IT审计发现汇总表", "stage": "delivery", "source": "结束阶段/C21-1  IT审计发现汇总表.xlsx"},
    {"code": "A27-1", "name": "IT审计总结备忘录", "stage": "delivery", "source": "结束阶段/A27-1 IT审计总结备忘录.docx"},
]

WORKPAPER_STAGE_FOLDERS = {
    "planning": "计划阶段",
    "execution": "执行阶段",
    "delivery": "结束阶段",
}

BASIC_WORKPAPER_BY_CODE = {spec["code"]: spec for spec in BASIC_WORKPAPER_SPECS}

_C22_TEST_POINT_PATTERN = re.compile(
    r"^(?:C22[.\-_/])?(?P<point>(?:SA|PE|PM)-\d+[A-Z]?(?:[.\-]\d+[A-Z]?)*)$",
    flags=re.IGNORECASE,
)


def normalize_workpaper_code(value: Any) -> str:
    return str(value or "").strip().upper()


def c22_test_point_code(value: Any) -> str:
    match = _C22_TEST_POINT_PATTERN.fullmatch(normalize_workpaper_code(value))
    return match.group("point").upper() if match else ""


def validate_workpaper_index_code(value: Any) -> str:
    code = normalize_workpaper_code(value)
    if not code:
        raise ValueError("底稿编号不能为空")
    test_point = c22_test_point_code(code)
    if test_point:
        raise ValueError(
            f"{test_point} 是 C22 底稿内的测试点，不是独立底稿编号；"
            "请选择 C22 底稿节点上传，测试点放在底稿内部或附件索引中。"
        )
    return code
