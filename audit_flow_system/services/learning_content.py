from __future__ import annotations


COURSEWARE = [
    {"title": "01-IT审计基础能力培训", "url": "/static/training/01-IT审计基础能力培训.html"},
    {"title": "02-IT审计财务知识：三大报表与业务数据", "url": "/static/training/02-IT审计财务知识_三大报表与业务数据.html"},
    {"title": "03-IT审计日常工作AI应用", "url": "/static/training/03-IT审计日常工作AI应用.html"},
]


WEEKS = [
    {"code": "W01", "week_no": 1, "title": "数据库、IT审计与只读查询基础", "summary": "数据库对象、IT审计概念、表结构和安全明细预览。", "guide_url": "/static/training/weeks/第01周_数据库与IT审计基础.md"},
    {"code": "W02", "week_no": 2, "title": "筛选、排序、空值与业财映射", "summary": "用明确范围筛选业务与日志数据，并解释潜在财务影响。", "guide_url": "/static/training/weeks/第02周_筛选条件与业财映射.md"},
    {"code": "W03", "week_no": 3, "title": "聚合、关联与审计证据链", "summary": "分组指标、表关联、重复风险和结果核对。", "guide_url": "/static/training/weeks/第03周_聚合关联与审计证据.md"},
    {"code": "W04", "week_no": 4, "title": "索引、EXPLAIN、性能与SQL安全", "summary": "识别全表扫描和危险SQL，在不改变口径的前提下优化。", "guide_url": "/static/training/weeks/第04周_索引性能与SQL安全.md"},
    {"code": "W05", "week_no": 5, "title": "Python数据库编程与AI辅助分析", "summary": "参数化查询、CSV导出、异常处理、隐私与复现。", "guide_url": "/static/training/weeks/第05周_Python数据库与AI辅助分析.md"},
    {"code": "W06", "week_no": 6, "title": "IMC、YUHU、SOHO综合项目", "summary": "选择项目轨道，提交基础核对、汇总、下钻和分析结论。", "guide_url": "/static/training/weeks/第06周_IMC_YUHU_SOHO综合项目.md"},
]


def _sql(code: str, week: int, title: str, prompt: str, scope: str, rules: dict, points: int = 20) -> dict:
    query_rules = {"query_enabled": True, "default_limit": 50, **rules}
    return {"code": code, "week_no": week, "title": title, "prompt": prompt, "question_type": "sql", "project_scope": scope, "rules": query_rules, "points": points}


def _text(code: str, week: int, title: str, prompt: str, scope: str = "general", points: int = 20) -> dict:
    return {"code": code, "week_no": week, "title": title, "prompt": prompt, "question_type": "text", "project_scope": scope, "rules": {}, "points": points}


QUESTIONS = [
    _sql("W01-Q01", 1, "IMC表清单", "列出imc库中的表，结果限制在100行以内。", "imc", {"allowed_databases": ["imc"], "required_keywords": ["show"]}),
    _sql("W01-Q02", 1, "YUHU日志结构", "查看yuhu.idm_登录与接入日志的字段结构。", "yuhu", {"allowed_databases": ["yuhu"], "required_keywords": ["describe"]}),
    _sql("W01-Q03", 1, "SOHO订单预览", "从soho.soho_ub_order_agg明确选择业务字段并预览不超过20行。", "soho", {"allowed_databases": ["soho"], "required_tables": ["soho.soho_ub_order_agg"], "require_limit": True, "max_limit": 20, "forbid_select_star": True}),
    _text("W01-Q04", 1, "审计查询前检查", "说明查询前的数据源、数据范围、数据完整性三个问题，并解释主键与普通索引的区别。"),

    _sql("W02-Q01", 2, "IMC期间筛选", "查询指定年度和月份的imc凭证明细，明确字段并限制200行。", "imc", {"allowed_databases": ["imc"], "required_tables": ["imc.imc_voucher"], "required_keywords": ["where"], "require_where": True, "require_limit": True, "max_limit": 200, "forbid_select_star": True}),
    _sql("W02-Q02", 2, "YUHU异常筛选", "按左闭右开时间范围筛选YUHU登录或接入异常，限制200行。", "yuhu", {"allowed_databases": ["yuhu"], "required_keywords": ["where"], "require_where": True, "require_limit": True, "max_limit": 200, "forbid_select_star": True}),
    _sql("W02-Q03", 2, "SOHO订单筛选", "按月份、平台或订单状态筛选SOHO订单，限制200行。", "soho", {"allowed_databases": ["soho"], "required_tables": ["soho.soho_ub_order_agg"], "require_where": True, "require_limit": True, "max_limit": 200, "forbid_select_star": True}),
    _text("W02-Q04", 2, "业财影响说明", "选择一项业务或日志异常，说明可能影响的报表项目、认定、当前证据和待补证据。"),

    _sql("W03-Q01", 3, "IMC平台聚合", "按平台统计限定期间的订单数和订单金额。", "imc", {"allowed_databases": ["imc"], "required_keywords": ["group", "where"], "require_where": True}),
    _sql("W03-Q02", 3, "YUHU日志聚合", "按日期或状态码汇总限定期间的日志事件。", "yuhu", {"allowed_databases": ["yuhu"], "required_keywords": ["group", "where"], "require_where": True}),
    _sql("W03-Q03", 3, "SOHO业务聚合", "按平台或店铺汇总SOHO订单数、订单金额和商品数量。", "soho", {"allowed_databases": ["soho"], "required_tables": ["soho.soho_ub_order_agg"], "required_keywords": ["group", "where"], "require_where": True}),
    _text("W03-Q04", 3, "关联与行数核对", "说明左右表粒度、关联键、关联前后行数、未匹配数和金额是否重复，并给出核对方法。"),

    _sql("W04-Q01", 4, "IMC执行计划", "使用EXPLAIN检查一条有期间范围和LIMIT的IMC明细查询。", "imc", {"allowed_databases": ["imc"], "required_keywords": ["explain", "where", "limit"], "require_where": True, "require_limit": True, "max_limit": 200}),
    _sql("W04-Q02", 4, "YUHU执行计划", "使用EXPLAIN检查一条按操作时间范围读取的YUHU查询。", "yuhu", {"allowed_databases": ["yuhu"], "required_keywords": ["explain", "where"], "require_where": True}),
    _sql("W04-Q03", 4, "SOHO执行计划", "使用EXPLAIN检查一条按月份或订单范围读取的SOHO查询。", "soho", {"allowed_databases": ["soho"], "required_keywords": ["explain", "where"], "require_where": True}),
    _text("W04-Q04", 4, "性能体检说明", "记录预期索引、估算扫描风险、优化前后差异，并说明为何业务口径没有变化。"),

    _sql("W05-Q01", 5, "参数化查询SQL", "提交供PyMySQL执行的只读查询主体，包含范围条件和LIMIT；参数值不得直接拼接。", "general", {"query_enabled": False, "allowed_databases": ["imc", "yuhu", "soho"], "require_where": True, "require_limit": True, "max_limit": 1000, "forbid_select_star": True}),
    _text("W05-Q02", 5, "Python核心实现", "提交连接、参数化execute、DictCursor、with关闭连接及UTF-8 BOM CSV导出的核心代码。"),
    _text("W05-Q03", 5, "错误与隐私处理", "说明空结果、连接超时、权限错误、密码保护和日志脱敏的处理方式。"),
    _text("W05-Q04", 5, "AI辅助复核记录", "记录使用AI完成的任务、输入边界、人工验证步骤、发现的问题和最终修改。"),

    _sql("W06-Q01", 6, "综合项目基础核对", "提交所选项目的数据范围、基础行数或金额核对SQL。", "general", {"allowed_databases": ["imc", "yuhu", "soho"], "require_where": True}),
    _sql("W06-Q02", 6, "综合项目汇总分析", "提交至少包含两个维度或三个指标的汇总SQL。", "general", {"allowed_databases": ["imc", "yuhu", "soho"], "required_keywords": ["group"], "require_where": True}),
    _sql("W06-Q03", 6, "综合项目明细下钻", "提交与汇总口径一致的异常或代表性明细下钻SQL，限制200行。", "general", {"allowed_databases": ["imc", "yuhu", "soho"], "require_where": True, "require_limit": True, "max_limit": 200, "forbid_select_star": True}),
    _text("W06-Q04", 6, "综合分析报告", "提交背景、数据源、期间、步骤、指标、异常线索、限制、待补证据和复现方式；注明IMC/YUHU/SOHO轨道。", points=140),
]
