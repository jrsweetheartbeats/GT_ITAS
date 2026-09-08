from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any


DISPLAY_NAMES = {
    "KMT": "康美婷", "HYT": "黄译潼", "CYX": "陈亦浠",
    "LSQ": "卢思齐", "WYX": "王勇轩", "KZJ": "柯治江", "KC": "况晨",
}

COMPETENCY_NAMES = {
    "financial_audit": "财务/会计", "itgc": "ITGC", "itac": "ITAC",
    "interface_ipe": "Interface/IPE", "data_analysis": "数据分析",
    "system_foundation": "IT技术基础", "communication": "客户沟通",
    "project_management": "项目管理", "ai_application": "AI应用",
}


class SlideParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.slides: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.depth = 0
        self.capture_tag = ""
        self.capture_text: list[str] = []
        self.list_depth = 0
        self.card_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set(str(attributes.get("class") or "").split())
        if tag == "section" and "slide" in classes:
            self.current = {"title": attributes.get("data-title") or "", "headings": [], "paragraphs": [], "items": [], "tables": []}
            self.slides.append(self.current)
            self.depth = 1
            return
        if not self.current:
            return
        self.depth += 1
        if tag in {"h1", "h2", "h3", "p", "li", "td", "th"}:
            self.capture_tag = tag
            self.capture_text = []

    def handle_data(self, data: str) -> None:
        if self.current and self.capture_tag:
            self.capture_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.current:
            return
        if tag == self.capture_tag:
            text = re.sub(r"\s+", " ", "".join(self.capture_text)).strip()
            if text and not re.search(r"\d+\s*/\s*\d+$", text):
                if tag.startswith("h"):
                    self.current["headings"].append(text)
                elif tag == "li":
                    self.current["items"].append(text)
                elif tag in {"td", "th"}:
                    if not self.current["tables"]:
                        self.current["tables"].append([])
                    self.current["tables"][-1].append(text)
                else:
                    self.current["paragraphs"].append(text)
            self.capture_tag = ""
            self.capture_text = []
        if tag == "table" and self.current:
            self.current["tables"].append([])
        if tag == "section":
            self.current = None
            self.depth = 0
        else:
            self.depth = max(0, self.depth - 1)


def clean_slides(path: Path) -> list[dict[str, Any]]:
    parser = SlideParser()
    parser.feed(path.read_text(encoding="utf-8"))
    for slide in parser.slides:
        slide["tables"] = [table for table in slide["tables"] if table]
    return parser.slides


def code_from_name(name: str) -> str:
    stem = re.sub(r"_第1个月.*$", "", name)
    reverse_names = {value: key for key, value in DISPLAY_NAMES.items()}
    return reverse_names.get(stem, stem).upper()


def questionnaire_rows(values: list[list[Any]]) -> list[dict[str, Any]]:
    header = next((index for index, row in enumerate(values) if row and str(row[0] or "").strip() == "模块"), None)
    if header is None:
        return []
    output = []
    for row in values[header + 1:]:
        row = list(row) + [None] * max(0, 7 - len(row))
        if not str(row[1] or "").strip():
            continue
        output.append({"module": row[0], "code": row[1], "question": row[2], "type": row[3], "options": row[4], "answer": row[5], "note": row[6]})
    return output


def derive_scores(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[tuple[float, str]]] = {code: [] for code in COMPETENCY_NAMES}
    for row in rows:
        answer = row.get("answer")
        question = str(row.get("question") or "")
        if any(word in question for word in ["WorkBuddy的熟练", "AI工具的熟练", "AI应用能力"]):
            match = re.match(r"\s*([A-E])", str(answer or "").upper())
            if match:
                buckets["ai_application"].append((ord(match.group(1)) - 64, question))
        if "评分" not in str(row.get("type") or "") or not isinstance(answer, (int, float)):
            continue
        codes = []
        if any(word in question for word in ["会计", "财务报表", "财审", "业务流程", "审计证据"]): codes.append("financial_audit")
        if any(word in question for word in ["用户权限", "职责分离", "程序变更", "系统运维", "日志", "备份", "ITGC"]): codes.append("itgc")
        if "ITAC" in question or "自动控制" in question: codes.append("itac")
        if any(word in question for word in ["接口", "Interface", "IPE", "系统报表", "关键报表"]): codes.append("interface_ipe")
        if any(word in question for word in ["Excel", "SQL", "Python", "数据分析", "数据库表结构"]): codes.append("data_analysis")
        if any(word in question for word in ["应用系统", "操作系统", "数据库", "技术"]): codes.append("system_foundation")
        if any(word in question for word in ["客户", "访谈", "资料需求", "汇报"]): codes.append("communication")
        if any(word in question for word in ["多任务", "项目推进", "项目管理"]): codes.append("project_management")
        for code in set(codes):
            buckets[code].append((float(answer), question))
    return {
        code: {"score": round(sum(score for score, _ in items) / len(items), 1), "note": "；".join(question for _, question in items)}
        for code, items in buckets.items() if items
    }


def plan_from_slides(code: str, file_name: str, slides: list[dict[str, Any]]) -> dict[str, Any]:
    cover = next((slide for slide in slides if slide["title"] == "封面"), slides[0])
    baseline = next((slide for slide in slides if slide["title"] == "当前基础"), {})
    objectives = next((slide for slide in slides if slide["title"] == "月度目标"), {})
    overview = next((slide for slide in slides if slide["title"] == "4周总览"), {})
    score_slide = next((slide for slide in slides if "评分" in slide["title"]), {})
    all_text = lambda slide: "\n".join(slide.get("paragraphs", []) + slide.get("items", []))
    goal = "；".join(objectives.get("paragraphs", []) + objectives.get("items", []))
    if not goal:
        goal = all_text(objectives)
    weekly_tasks = []
    overview_text = " ".join(overview.get("headings", []) + overview.get("paragraphs", []) + overview.get("items", []))
    for week_no in range(1, 5):
        detail = next((slide for slide in slides if slide["title"] == f"第{week_no}周"), {})
        related = [slide for slide in slides if str(slide["title"]).startswith(f"第{week_no}周") and slide is not detail]
        heading = next((text for text in detail.get("headings", []) if f"第{week_no}周" in text), f"第{week_no}周")
        topic = re.sub(r"^第\d+周[｜|·\s]*", "", heading).strip() or heading
        exercise = "\n".join(text for slide in related for text in slide.get("paragraphs", []) + slide.get("items", []))
        detail_text = all_text(detail)
        deliverable = ""
        acceptance = ""
        for slide in related:
            table = next(iter(slide.get("tables", [])), [])
            if table:
                deliverable = "；".join(table[3::3]) if len(table) >= 6 else "；".join(table)
            combined = " ".join(slide.get("paragraphs", []))
            match = re.search(r"(?:通过标准|当周验收|验收)[：:]\s*(.+)", combined)
            if match:
                acceptance = match.group(1)
        if not acceptance:
            pattern = rf"第{week_no}周.*?验收[：:]\s*([^。]+)"
            match = re.search(pattern, overview_text)
            acceptance = match.group(1) if match else "完成当周交付物并通过导师Review"
        weekly_tasks.append({"weekNo": week_no, "topic": topic, "learningContent": detail_text, "exerciseCase": exercise, "deliverable": deliverable or f"第{week_no}周可Review成果", "acceptanceCriteria": acceptance})
    return {
        "title": next(iter(cover.get("headings", [])), f"{code} 第1个月特别培养计划"),
        "monthGoal": goal or all_text(cover),
        "generationBasis": next((text for text in cover.get("paragraphs", []) if "依据" in text), f"依据{code}调研问卷生成"),
        "rationale": next((text for text in cover.get("paragraphs", []) if "培养重点" in text), all_text(cover)),
        "advantages": "\n".join(baseline.get("items", [])[:5]),
        "weaknesses": "\n".join(baseline.get("items", [])[5:10]),
        "scoreText": all_text(score_slide),
        "sourceReference": file_name,
        "tasks": weekly_tasks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questionnaires-json", required=True)
    parser.add_argument("--plans-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    questionnaires = json.loads(Path(args.questionnaires_json).read_text(encoding="utf-8"))
    employees: dict[str, dict[str, Any]] = {}
    for book in questionnaires:
        code = re.sub(r"^调研问卷_", "", book["fileName"], flags=re.I).removesuffix(".xlsx").upper()
        rows = questionnaire_rows(book["values"])
        employees[code] = {
            "code": code, "name": DISPLAY_NAMES.get(code, code), "questionnaire": {"answers": rows},
            "competencies": derive_scores(rows), "sourceReference": book["fileName"],
        }
    plans_dir = Path(args.plans_dir)
    for path in sorted(plans_dir.glob("*.html")):
        if "总目录" in path.name:
            continue
        code = code_from_name(path.stem)
        plan = plan_from_slides(code, path.name, clean_slides(path))
        employee = employees.setdefault(code, {"code": code, "name": DISPLAY_NAMES.get(code, code), "questionnaire": {}, "competencies": {}, "sourceReference": ""})
        employee["name"] = DISPLAY_NAMES.get(code, employee["name"])
        employee["plan"] = plan
        employee["advantages"] = plan["advantages"]
        employee["weaknesses"] = plan["weaknesses"]
    output = {"competencyDimensions": [{"code": code, "name": name, "sortOrder": index * 10} for index, (code, name) in enumerate(COMPETENCY_NAMES.items(), start=1)], "employees": list(employees.values())}
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
