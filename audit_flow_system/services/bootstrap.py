from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.security import (
    DEFAULT_MODULE_ORDER,
    DEFAULT_PASSWORD_POLICY,
    get_setting,
    hash_password,
    normalize_module_order,
    set_setting,
    verify_password,
)
from ..core.config import initial_admin_password, is_production_environment
from ..models import (
    AutomationRule,
    CompetencyDimension,
    DevelopmentEmployee,
    DevelopmentPlan,
    EmployeeCompetency,
    FeatureModule,
    MonthlyPlan,
    PracticeQuestion,
    Role,
    RoleFeaturePermission,
    TrainingWeek,
    User,
    WeeklyTask,
    WorkpaperTemplate,
)
from .learning_content import COURSEWARE, QUESTIONS, WEEKS
from .projects import DEFAULT_TEMPLATE_FILES


DEFAULT_FEATURE_MODULES = [
    ("home", "项目首页", "全部项目主数据、团队成员和客户信息总览"),
    ("dashboard", "首页驾驶舱", "项目进度、资料缺口、复核退回和质量风险总览"),
    ("projectWorkspace", "项目工作台", "项目上下文、成员、范围和工作流入口"),
    ("scopeCenter", "审计范围", "系统清单、范围理由、置信度和风险识别"),
    ("pbcCenter", "PBC资料", "客户资料清单、缺口、责任人和关联底稿"),
    ("workpaperExecution", "底稿详情", "底稿文件树、编制复核、附件和问题联动"),
    ("autoCheck", "自动检核", "规则检查结果、定位、证据和整改建议"),
    ("reviewCenter", "复核中心", "复核轮次、退回意见、责任人和关闭状态"),
    ("findingKanban", "问题整改", "系统和人工问题的整改流转看板"),
    ("qualityDashboard", "质量看板", "跨项目质量风险、问题分布和项目压力"),
    ("resourcePlan", "人员计划", "项目成员排期、周期和进度管理"),
    ("architecture", "功能架构", "ITAS 生命周期模块和数据对象说明"),
    ("templates", "模板库", "默认底稿模板下载和版本查看"),
    ("learning", "学习刷题", "六周课程、SQL静态校验、作业提交、订正和批阅"),
    ("development", "人才培养", "能力画像、滚动培养计划、周任务、Review问题和月度复盘"),
    ("clients", "客户信息", "客户和企业 IT 联系人维护"),
    ("projects", "项目管理", "项目主数据、成员和联系人维护"),
    ("workpapers", "底稿管理", "IT 审计底稿登记和流转"),
    ("attachments", "附件管理", "附件索引、扫描和引用关系"),
    ("issueDashboard", "问题看板", "项目问题和规则问题分布统计"),
    ("materials", "资料清单", "客户资料需求和上传记录"),
    ("reviews", "复核记录", "底稿复核流程和问题记录"),
    ("quality", "质量问题", "自动检核和人工复核问题维护"),
    ("people", "人员角色", "用户、角色和权限配置"),
    ("config", "系统配置", "密码策略、功能排序和基础配置"),
]

DEFAULT_AUDIT_USERS = [
    ("ita_lhy", "李辉云", "partner"),
    ("ita_rdy", "任德昀", "director"),
    ("ita_flf", "凡兰芬", "senior_manager"),
    ("ita_lr", "李瑞", "manager"),
    ("ita_kzj", "柯治江", "preparer"),
    ("ita_kc", "况晨", "preparer"),
    ("ita_kmt", "康美婷", "preparer"),
    ("ita_lsq", "卢思齐", "preparer"),
    ("ita_hyt", "黄译潼", "preparer"),
    ("ita_wyx", "王勇轩", "preparer"),
]


DEFAULT_ROLE_PERMISSIONS = {
    "partner": {
        "view": {"home", "dashboard", "projectWorkspace", "workpaperExecution", "workpapers", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "reviewCenter", "reviews", "templates", "architecture", "learning", "development"},
        "edit": {"reviewCenter", "reviews", "quality"},
        "manage": set(),
    },
    "director": {
        "view": {"home", "dashboard", "projectWorkspace", "workpaperExecution", "workpapers", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "reviewCenter", "reviews", "templates", "architecture", "learning", "development"},
        "edit": {"reviewCenter", "reviews", "quality"},
        "manage": set(),
    },
    "senior_manager": {
        "view": {"home", "dashboard", "projectWorkspace", "workpaperExecution", "workpapers", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "reviewCenter", "reviews", "templates", "architecture", "learning", "development"},
        "edit": {"reviewCenter", "reviews", "quality"},
        "manage": set(),
    },
    "quality": {
        "view": {"home", "dashboard", "projectWorkspace", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "reviewCenter", "reviews", "workpapers", "attachments", "templates", "architecture", "learning", "development"},
        "edit": {"reviewCenter", "reviews", "quality", "workpapers", "attachments", "development"},
        "manage": set(),
    },
    "manager": {
        "view": {"home", "dashboard", "projectWorkspace", "projects", "clients", "scopeCenter", "pbcCenter", "workpaperExecution", "attachments", "autoCheck", "reviewCenter", "findingKanban", "workpapers", "ruleVisualization", "ruleInspection", "reviews", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "resourcePlan", "templates", "architecture", "learning", "development"},
        "edit": {"projects", "clients", "scopeCenter", "pbcCenter", "workpaperExecution", "attachments", "autoCheck", "reviewCenter", "findingKanban", "workpapers", "ruleVisualization", "reviews", "quality", "resourcePlan", "development"},
        "manage": set(),
    },
    "preparer": {
        "view": {"home", "dashboard", "projectWorkspace", "scopeCenter", "pbcCenter", "workpaperExecution", "attachments", "autoCheck", "findingKanban", "workpapers", "reviews", "templates", "architecture", "learning", "development"},
        "edit": {"workpaperExecution", "attachments", "findingKanban", "workpapers", "learning", "development"},
        "manage": set(),
    },
    "client_contact": {
        "view": {"home", "dashboard", "projectWorkspace", "pbcCenter", "attachments"},
        "edit": {"attachments"},
        "manage": set(),
    },
}


def seed_defaults(db: Session) -> None:
    # Production must never silently create a known credential.  Development
    # demo users also require an explicit password and are not seeded in prod.
    admin_password = initial_admin_password(required=is_production_environment())
    admin: User | None = None
    set_setting(db, "password_policy", get_setting(db, "password_policy", DEFAULT_PASSWORD_POLICY))
    set_setting(db, "module_order", normalize_module_order(get_setting(db, "module_order", DEFAULT_MODULE_ORDER)))
    if db.execute(select(func.count(Role.id))).scalar_one() == 0:
        roles = [
            Role(code="admin", name="系统管理员", rank=1000, can_review=True, description="维护用户、角色和系统配置"),
            Role(code="partner", name="合伙人", rank=900, can_review=True, description="最终项目复核"),
            Role(code="quality", name="质控人员", rank=880, can_review=True, description="质量控制复核"),
            Role(code="director", name="总监", rank=850, can_review=True, description="项目质量和重大判断复核"),
            Role(code="senior_manager", name="高级经理", rank=780, can_review=True, description="高级经理复核"),
            Role(code="manager", name="经理", rank=700, can_review=True, description="经理复核"),
            Role(code="preparer", name="执行人员", rank=500, can_review=False, description="底稿编制与证据整理"),
            Role(code="client_contact", name="企业对接人", rank=100, can_review=False, description="被审计单位资料对接"),
        ]
        db.add_all(roles)
        db.flush()
        if not admin_password:
            raise RuntimeError("首次初始化管理员请设置 AUDIT_FLOW_INITIAL_ADMIN_PASSWORD")
        db.add(User(username="ita_admin", display_name="系统管理员", role_id=roles[0].id, password_hash=hash_password(admin_password)))
    else:
        admin = db.execute(select(User).where(User.username == "ita_admin")).scalar_one_or_none()
        admin_role = db.execute(select(Role).where(Role.code == "admin")).scalar_one_or_none()
        if admin is None and admin_role is not None:
            if not admin_password:
                raise RuntimeError("首次初始化管理员请设置 AUDIT_FLOW_INITIAL_ADMIN_PASSWORD")
            db.add(User(username="ita_admin", display_name="系统管理员", role_id=admin_role.id, password_hash=hash_password(admin_password)))
        elif admin is not None and not admin.password_hash:
            raise RuntimeError("管理员账号缺少密码，请通过受控运维流程重置密码")
    if is_production_environment():
        disable_demo_audit_users(db)
        if admin is not None and verify_password("123", admin.password_hash):
            admin.password_hash = hash_password(admin_password)
    else:
        seed_audit_users(db, admin_password)

    if db.execute(select(func.count(AutomationRule.id))).scalar_one() == 0:
        rules = [
            AutomationRule(
                code="GLOBAL-001",
                name="底稿基本信息完整性",
                category="全局扫描",
                severity="high",
                description="检查项目年度、底稿编码、编制人和文件路径等关键字段。",
            ),
            AutomationRule(
                code="ATT-001",
                name="附件索引唯一性",
                category="附件管理",
                severity="high",
                description="检查同一项目下附件索引号是否为空或重复。",
            ),
            AutomationRule(
                code="ATT-002",
                name="附件引用一致性",
                category="附件管理",
                severity="medium",
                description="检查底稿引用说明中是否包含附件索引号。",
            ),
            AutomationRule(
                code="FLOW-001",
                name="底稿复核流转完整性",
                category="复核流程",
                severity="medium",
                description="检查已提交底稿是否建立经理至质控/合伙人的复核步骤。",
            ),
        ]
        db.add_all(rules)
    seed_feature_modules(db)
    seed_training_content(db)
    seed_development_content(db)
    seed_workpaper_templates(db)
    db.commit()


def seed_development_content(db: Session) -> None:
    seed_path = Path(__file__).resolve().parents[1] / "data" / "development_seed.json"
    if not seed_path.exists():
        return
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    dimensions = {row.code: row for row in db.execute(select(CompetencyDimension)).scalars().all()}
    for item in payload.get("competencyDimensions", []):
        row = dimensions.get(item["code"])
        if row is None:
            row = CompetencyDimension(code=item["code"], name=item["name"])
            db.add(row)
            db.flush()
            dimensions[row.code] = row
        row.name = item["name"]
        row.sort_order = int(item.get("sortOrder") or 0)
        row.enabled = True
    employees = {row.code: row for row in db.execute(select(DevelopmentEmployee)).scalars().all()}
    users = db.execute(select(User)).scalars().all()
    users_by_name = {row.display_name: row for row in users}
    mentor = users_by_name.get("李瑞")
    for item in payload.get("employees", []):
        code = str(item["code"]).upper()
        row = employees.get(code)
        if row is None:
            matched_user = users_by_name.get(item.get("name", ""))
            row = DevelopmentEmployee(code=code, name=item.get("name") or code, user_id=matched_user.id if matched_user else None)
            db.add(row)
            db.flush()
            employees[code] = row
        row.name = item.get("name") or row.name
        row.current_role = row.current_role or "IT审计人员"
        row.mentor_user_id = row.mentor_user_id or (mentor.id if mentor else None)
        row.questionnaire_json = json.dumps(item.get("questionnaire") or {}, ensure_ascii=False)
        row.source_reference = item.get("sourceReference") or row.source_reference
        row.advantages = item.get("advantages") or row.advantages
        row.weaknesses = item.get("weaknesses") or row.weaknesses
        plan_data = item.get("plan") or {}
        row.current_focus = row.current_focus or plan_data.get("monthGoal", "")
        for competency_code, score_data in (item.get("competencies") or {}).items():
            dimension = dimensions.get(competency_code)
            if dimension is None:
                continue
            exists = db.execute(select(EmployeeCompetency.id).where(EmployeeCompetency.employee_id == row.id, EmployeeCompetency.competency_id == dimension.id, EmployeeCompetency.source == "questionnaire_seed")).scalar_one_or_none()
            if exists is None:
                db.add(EmployeeCompetency(employee_id=row.id, competency_id=dimension.id, score=float(score_data["score"]), assessed_on=date(2026, 8, 1), source="questionnaire_seed", note=score_data.get("note", "")))
        if not plan_data:
            continue
        plan = db.execute(select(DevelopmentPlan).where(DevelopmentPlan.employee_id == row.id, DevelopmentPlan.source_reference == plan_data.get("sourceReference", ""))).scalar_one_or_none()
        if plan is None:
            plan = DevelopmentPlan(employee_id=row.id, title="2026年度培养计划", plan_type="annual", half_year_goal=row.half_year_goal, year_goal=row.year_goal, status="active", source_type="questionnaire_plan", source_reference=plan_data.get("sourceReference", ""))
            db.add(plan)
            db.flush()
            month = MonthlyPlan(development_plan_id=plan.id, month_no=1, title=plan_data.get("title") or "第1个月培养计划", month_goal=plan_data.get("monthGoal", ""), generation_basis=plan_data.get("generationBasis", ""), rationale=plan_data.get("rationale", ""), status="published", generated_by="source_import", published_at=datetime.utcnow())
            db.add(month)
            db.flush()
            for task in plan_data.get("tasks", []):
                db.add(WeeklyTask(monthly_plan_id=month.id, week_no=int(task.get("weekNo") or 1), topic=task.get("topic") or "周训练", learning_content=task.get("learningContent", ""), exercise_case=task.get("exerciseCase", ""), deliverable=task.get("deliverable", ""), acceptance_criteria=task.get("acceptanceCriteria", ""), owner_user_id=mentor.id if mentor else None))


def seed_audit_users(db: Session, password: str) -> None:
    if not password:
        return
    roles_by_code = {row.code: row for row in db.execute(select(Role)).scalars().all()}
    users_by_username = {row.username: row for row in db.execute(select(User)).scalars().all()}
    users_by_display_name = {row.display_name: row for row in users_by_username.values()}
    for username, display_name, role_code in DEFAULT_AUDIT_USERS:
        role = roles_by_code.get(role_code)
        if role is None:
            continue
        user = users_by_username.get(username) or users_by_display_name.get(display_name)
        if user is None:
            db.add(
                User(
                    username=username,
                    display_name=display_name,
                    role_id=role.id,
                    password_hash=hash_password(password),
                )
            )
            continue
        user.display_name = display_name
        user.role_id = role.id
        # Do not repair an incomplete account with a predictable password.


def disable_demo_audit_users(db: Session) -> None:
    """Demo identities are available only in development environments."""
    usernames = [username for username, _, _ in DEFAULT_AUDIT_USERS]
    for user in db.execute(select(User).where(User.username.in_(usernames))).scalars():
        user.status = "disabled"


def seed_feature_modules(db: Session) -> None:
    modules_by_code = {
        row.code: row for row in db.execute(select(FeatureModule)).scalars().all()
    }
    for index, (code, name, description) in enumerate(DEFAULT_FEATURE_MODULES, start=1):
        module = modules_by_code.get(code)
        if module is None:
            module = FeatureModule(code=code, name=name)
            db.add(module)
            db.flush()
            modules_by_code[code] = module
        module.name = name
        module.description = description
        module.sort_order = index * 10
        module.enabled = True

    admin_role = db.execute(select(Role).where(Role.code == "admin")).scalar_one_or_none()
    if admin_role is None:
        return
    existing = {
        row.feature_module_id: row
        for row in db.execute(
            select(RoleFeaturePermission).where(RoleFeaturePermission.role_id == admin_role.id)
        ).scalars()
    }
    for module in modules_by_code.values():
        permission = existing.get(module.id)
        if permission is None:
            permission = RoleFeaturePermission(role_id=admin_role.id, feature_module_id=module.id)
            db.add(permission)
        permission.can_view = True
        permission.can_edit = True
        permission.can_manage = True

    roles_by_code = {row.code: row for row in db.execute(select(Role)).scalars().all()}
    for role_code, spec in DEFAULT_ROLE_PERMISSIONS.items():
        role = roles_by_code.get(role_code)
        if role is None:
            continue
        existing = {
            row.feature_module_id: row
            for row in db.execute(
                select(RoleFeaturePermission).where(RoleFeaturePermission.role_id == role.id)
            ).scalars()
        }
        for module_code, module in modules_by_code.items():
            if module.id in existing:
                # Quality teachers need to receive and register workpaper files,
                # while preserving all other existing role customizations.
                if role_code == "quality" and module_code in {"workpapers", "attachments"}:
                    existing[module.id].can_view = True
                    existing[module.id].can_edit = True
                continue
            can_manage = module_code in spec["manage"]
            can_edit = can_manage or module_code in spec["edit"]
            can_view = can_edit or module_code in spec["view"]
            if not can_view:
                continue
            db.add(
                RoleFeaturePermission(
                    role_id=role.id,
                    feature_module_id=module.id,
                    can_view=True,
                    can_edit=can_edit,
                    can_manage=can_manage,
                )
            )


def seed_training_content(db: Session) -> None:
    weeks_by_no = {row.week_no: row for row in db.execute(select(TrainingWeek)).scalars().all()}
    courseware_json = json.dumps(COURSEWARE, ensure_ascii=False)
    for item in WEEKS:
        week = weeks_by_no.get(item["week_no"])
        if week is None:
            week = TrainingWeek(code=item["code"], week_no=item["week_no"], title=item["title"])
            db.add(week)
            db.flush()
            weeks_by_no[item["week_no"]] = week
        week.code = item["code"]
        week.title = item["title"]
        week.summary = item["summary"]
        week.learning_markdown = f"完整学习指导：{item['guide_url']}"
        week.courseware_json = courseware_json
        week.sort_order = item["week_no"] * 10
        week.enabled = True

    questions_by_code = {row.code: row for row in db.execute(select(PracticeQuestion)).scalars().all()}
    for index, item in enumerate(QUESTIONS, start=1):
        question = questions_by_code.get(item["code"])
        if question is None:
            question = PracticeQuestion(
                training_week_id=weeks_by_no[item["week_no"]].id,
                code=item["code"],
                title=item["title"],
                prompt=item["prompt"],
            )
            db.add(question)
        question.training_week_id = weeks_by_no[item["week_no"]].id
        question.title = item["title"]
        question.prompt = item["prompt"]
        question.question_type = item["question_type"]
        question.project_scope = item["project_scope"]
        question.validation_rules_json = json.dumps(item["rules"], ensure_ascii=False)
        question.points = item["points"]
        question.sort_order = index * 10
        question.enabled = True


def seed_workpaper_templates(db: Session) -> None:
    existing = {
        (row.code, row.version): row
        for row in db.execute(select(WorkpaperTemplate)).scalars().all()
    }
    for index, spec in enumerate(DEFAULT_TEMPLATE_FILES, start=1):
        key = (spec["code"], "default")
        template = existing.get(key)
        if template is None:
            template = WorkpaperTemplate(code=spec["code"], version="default")
            db.add(template)
        template.name = spec["name"]
        template.stage = spec["stage"]
        template.source_path = spec["source"]
        template.applicable_year = int(spec.get("applicable_year", "2025"))
        template.update_note = spec.get("update_note", "2025 年默认底稿模板")
        template.is_latest = True
        template.sort_order = index * 10
        template.default_enabled = True
