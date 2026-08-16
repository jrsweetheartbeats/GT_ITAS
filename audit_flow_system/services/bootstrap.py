from __future__ import annotations

import json
import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.security import (
    DEFAULT_MODULE_ORDER,
    DEFAULT_PASSWORD_POLICY,
    get_setting,
    hash_password,
    normalize_module_order,
    set_setting,
)
from ..models import (
    AutomationRule,
    FeatureModule,
    PracticeQuestion,
    Role,
    RoleFeaturePermission,
    TrainingWeek,
    User,
    WorkpaperTemplate,
)
from .learning_content import COURSEWARE, QUESTIONS, WEEKS
from .projects import DEFAULT_TEMPLATE_FILES


DEFAULT_FEATURE_MODULES = [
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

DEFAULT_AUDIT_USERS: list[tuple[str, str, str]] = []


def initial_password() -> str:
    value = os.getenv("AUDIT_FLOW_INITIAL_PASSWORD", "").strip()
    if not value:
        raise RuntimeError("首次初始化前必须设置 AUDIT_FLOW_INITIAL_PASSWORD")
    return value


DEFAULT_ROLE_PERMISSIONS = {
    "partner": {
        "view": {"dashboard", "projectWorkspace", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "reviewCenter", "reviews", "templates", "architecture", "learning"},
        "edit": {"reviewCenter", "reviews", "quality"},
        "manage": {"learning"},
    },
    "director": {
        "view": {"dashboard", "projectWorkspace", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "reviewCenter", "reviews", "templates", "architecture", "learning"},
        "edit": {"reviewCenter", "reviews", "quality"},
        "manage": {"learning"},
    },
    "senior_manager": {
        "view": {"dashboard", "projectWorkspace", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "reviewCenter", "reviews", "templates", "architecture", "learning"},
        "edit": {"reviewCenter", "reviews", "quality"},
        "manage": {"learning"},
    },
    "quality": {
        "view": {"dashboard", "projectWorkspace", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "reviewCenter", "reviews", "templates", "architecture", "learning"},
        "edit": {"reviewCenter", "reviews", "quality"},
        "manage": {"learning"},
    },
    "manager": {
        "view": {"dashboard", "projectWorkspace", "projects", "clients", "scopeCenter", "pbcCenter", "workpaperExecution", "attachments", "autoCheck", "reviewCenter", "findingKanban", "workpapers", "ruleVisualization", "ruleInspection", "reviews", "qualityDashboard", "issueDashboard", "projectOverview", "quality", "resourcePlan", "templates", "architecture", "learning"},
        "edit": {"projects", "clients", "scopeCenter", "pbcCenter", "workpaperExecution", "attachments", "autoCheck", "reviewCenter", "findingKanban", "workpapers", "ruleVisualization", "reviews", "quality", "resourcePlan"},
        "manage": {"learning"},
    },
    "preparer": {
        "view": {"dashboard", "projectWorkspace", "scopeCenter", "pbcCenter", "workpaperExecution", "attachments", "autoCheck", "findingKanban", "workpapers", "reviews", "templates", "architecture", "learning"},
        "edit": {"workpaperExecution", "attachments", "findingKanban", "workpapers", "learning"},
        "manage": set(),
    },
    "client_contact": {
        "view": {"dashboard", "projectWorkspace", "pbcCenter", "attachments"},
        "edit": {"attachments"},
        "manage": set(),
    },
}


def seed_defaults(db: Session) -> None:
    set_setting(db, "password_policy", get_setting(db, "password_policy", DEFAULT_PASSWORD_POLICY))
    set_setting(db, "module_order", normalize_module_order(get_setting(db, "module_order", DEFAULT_MODULE_ORDER)))
    if db.execute(select(func.count(Role.id))).scalar_one() == 0:
        password = initial_password()
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
        db.add(User(username="admin", display_name="系统管理员", role_id=roles[0].id, password_hash=hash_password(password)))
    else:
        admin = db.execute(select(User).where(User.username == "admin")).scalar_one_or_none()
        admin_role = db.execute(select(Role).where(Role.code == "admin")).scalar_one_or_none()
        if admin is None and admin_role is not None:
            db.add(User(username="admin", display_name="系统管理员", role_id=admin_role.id, password_hash=hash_password(initial_password())))
        elif admin is not None and not admin.password_hash:
            admin.password_hash = hash_password(initial_password())
    seed_audit_users(db, os.getenv("AUDIT_FLOW_INITIAL_PASSWORD", "").strip())

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
    seed_workpaper_templates(db)
    db.commit()


def seed_audit_users(db: Session, password: str = "") -> None:
    roles_by_code = {row.code: row for row in db.execute(select(Role)).scalars().all()}
    users_by_username = {row.username: row for row in db.execute(select(User)).scalars().all()}
    users_by_display_name = {row.display_name: row for row in users_by_username.values()}
    for username, display_name, role_code in DEFAULT_AUDIT_USERS:
        role = roles_by_code.get(role_code)
        if role is None:
            continue
        user = users_by_username.get(username) or users_by_display_name.get(display_name)
        if user is None:
            if not password:
                raise RuntimeError("创建默认审计用户前必须设置 AUDIT_FLOW_INITIAL_PASSWORD")
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
        if not user.password_hash:
            if not password:
                raise RuntimeError("补充默认用户密码前必须设置 AUDIT_FLOW_INITIAL_PASSWORD")
            user.password_hash = hash_password(password)


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

    questions_by_code = {
        row.code: row for row in db.execute(select(PracticeQuestion)).scalars().all()
    }
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
