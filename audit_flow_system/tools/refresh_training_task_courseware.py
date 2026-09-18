"""Replace legacy shared training links with task-specific protected courseware."""
from __future__ import annotations

from sqlalchemy import select

from ..core.db import SessionLocal
from ..models import DevelopmentLearningMaterial, DevelopmentTrainingTask


COURSEWARE = ("学习课件", "完整介绍本任务的概念、学习要求、注意事项和风险实质。")


def refresh() -> int:
    """Update existing records in place so material-read history remains available."""
    with SessionLocal() as db:
        tasks = db.execute(select(DevelopmentTrainingTask)).scalars().all()
        for task in tasks:
            materials = sorted(task.materials, key=lambda row: (row.sort_order, row.id))
            if materials:
                material = materials[0]
            else:
                material = DevelopmentLearningMaterial(task_id=task.id)
                db.add(material)
            label, description = COURSEWARE
            material.title = f"{task.title}｜{label}"
            material.material_type = "itas_page"
            material.course_scope = "personal"
            material.url = f"/api/development/tasks/{task.id}/courseware"
            material.description = description
            material.sort_order = 0
            for material in materials[1:]:
                db.delete(material)
        db.commit()
        return len(tasks)


def main() -> None:
    print(f"已更新 {refresh()} 项培养任务的专属课程内容。")


if __name__ == "__main__":
    main()
