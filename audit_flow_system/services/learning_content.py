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
    _sql("W01-Q01", 1, "IMC表清单", "列出imc库中的表，结果限制在100行以内。", "imc", {"allowed_databases": ["imc"], "required_keywords": ["show"], "table_hints": ["无需指定数据表，使用 SHOW TABLES FROM imc"]}),
    _sql("W01-Q02", 1, "YUHU日志结构", "查看yuhu.IDM_登录与接入日志的字段结构。", "yuhu", {"allowed_databases": ["yuhu"], "required_keywords": ["describe"], "table_hints": ["yuhu.IDM_登录与接入日志"]}),
    _sql("W01-Q03", 1, "SOHO订单预览", "从soho.soho_ub_order_agg明确选择业务字段并预览不超过20行。", "soho", {"allowed_databases": ["soho"], "required_tables": ["soho.soho_ub_order_agg"], "require_limit": True, "max_limit": 20, "forbid_select_star": True, "table_hints": ["soho.soho_ub_order_agg"]}),
    _text("W01-Q04", 1, "审计查询前检查", "说明查询前的数据源、数据范围、数据完整性三个问题，并解释主键与普通索引的区别。"),

    _sql(
        "W02-Q01", 2, "IMC期间筛选",
        "从 imc.imc_voucher 查询会计年度为2024、期间为12的凭证明细。必须返回：日期、会计年度、期间、凭证字、凭证号、摘要、科目编码、科目全名、借方金额、贷方金额、来源系统；不得使用SELECT *；必须同时使用WHERE限定会计年度和期间，并写明LIMIT 200。",
        "imc",
        {
            "allowed_databases": ["imc"],
            "required_tables": ["imc.imc_voucher"],
            "required_keywords": ["where"],
            "required_select_columns": ["日期", "会计年度", "期间", "凭证字", "凭证号", "摘要", "科目编码", "科目全名", "借方金额", "贷方金额", "来源系统"],
            "required_equalities": {"会计年度": 2024, "期间": 12},
            "require_where": True,
            "require_limit": True,
            "exact_limit": 200,
            "max_limit": 200,
            "forbid_select_star": True,
            "verify_execution": True,
            "require_nonempty_result": True,
            "expected_result_values": {"会计年度": 2024, "期间": 12},
            "table_hints": ["imc.imc_voucher（会计年度=2024、期间=12）"],
        },
    ),
    _sql("W02-Q02", 2, "YUHU异常筛选", "按左闭右开时间范围筛选YUHU登录或接入异常，限制200行。", "yuhu", {"allowed_databases": ["yuhu"], "required_tables": ["yuhu.IDM_登录与接入日志"], "required_keywords": ["where"], "require_where": True, "require_limit": True, "max_limit": 200, "forbid_select_star": True, "table_hints": ["yuhu.IDM_登录与接入日志"]}),
    _sql("W02-Q03", 2, "SOHO订单筛选", "按月份、平台或订单状态筛选SOHO订单，限制200行。", "soho", {"allowed_databases": ["soho"], "required_tables": ["soho.soho_ub_order_agg"], "require_where": True, "require_limit": True, "max_limit": 200, "forbid_select_star": True, "table_hints": ["soho.soho_ub_order_agg"]}),
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


EXACT_SQL_ANSWERS = {
    "W01-Q01": {
        "prompt": "列出 imc 数据库中的全部数据表。结果必须与数据库返回的完整表清单一致。",
        "answer_sql": "SHOW TABLES FROM imc",
    },
    "W01-Q02": {
        "prompt": "查看 yuhu.IDM_登录与接入日志 的完整字段结构，字段定义及顺序必须与数据库一致。",
        "answer_sql": "DESCRIBE yuhu.IDM_登录与接入日志",
    },
    "W01-Q03": {
        "prompt": "查询 soho.soho_ub_order_agg 中 month_key='2025-06' 的订单，依次返回 order_key、order_id、order_time、platform、shop_name、order_amount、order_status，按 order_key 升序并限制20行。",
        "answer_sql": "SELECT order_key, order_id, order_time, platform, shop_name, order_amount, order_status FROM soho.soho_ub_order_agg WHERE month_key = '2025-06' ORDER BY order_key LIMIT 20",
    },
    "W02-Q01": {
        "prompt": "从 imc.imc_voucher 查询会计年度为2024、期间为12的凭证明细。依次返回：日期、会计年度、期间、凭证字、凭证号、摘要、科目编码、科目全名、借方金额、贷方金额、来源系统；按上述全部字段依次升序排序，并写明 LIMIT 200。",
        "answer_sql": "SELECT `日期`, `会计年度`, `期间`, `凭证字`, `凭证号`, `摘要`, `科目编码`, `科目全名`, `借方金额`, `贷方金额`, `来源系统` FROM imc.imc_voucher WHERE `会计年度` = 2024 AND `期间` = 12 ORDER BY `日期`, `凭证字`, `凭证号`, `科目编码`, `摘要`, `借方金额`, `贷方金额`, `来源系统` LIMIT 200",
    },
    "W02-Q02": {
        "prompt": "查询 yuhu.IDM_登录与接入日志 中操作时间在 2025-07-01 00:00:00（含）至 2025-07-02 00:00:00（不含）且日志标题不等于“登录成功”的记录。依次返回 id、日志标题、操作用户、操作时间、客户端IP、响应时间，按 id 升序并限制200行。",
        "answer_sql": "SELECT id, `日志标题`, `操作用户`, `操作时间`, `客户端IP`, `响应时间` FROM yuhu.IDM_登录与接入日志 WHERE `操作时间` >= '2025-07-01 00:00:00' AND `操作时间` < '2025-07-02 00:00:00' AND `日志标题` <> '登录成功' ORDER BY id LIMIT 200",
    },
    "W02-Q03": {
        "prompt": "查询 soho.soho_ub_order_agg 中 month_key='2025-06'、platform='天猫'、order_status='已确认'的订单。依次返回 order_key、order_id、order_time、platform、shop_name、order_amount、order_status，按 order_key 升序并限制200行。",
        "answer_sql": "SELECT order_key, order_id, order_time, platform, shop_name, order_amount, order_status FROM soho.soho_ub_order_agg WHERE month_key = '2025-06' AND platform = '天猫' AND order_status = '已确认' ORDER BY order_key LIMIT 200",
    },
    "W03-Q01": {
        "prompt": "对 imc.dws_order_agg_month_platform 中2024年1至6月数据按平台汇总。依次返回平台、SUM(订单数量) AS 订单数量、ROUND(SUM(销售金额),2) AS 销售金额，按平台升序。",
        "answer_sql": "SELECT `平台`, SUM(`订单数量`) AS `订单数量`, ROUND(SUM(`销售金额`), 2) AS `销售金额` FROM imc.dws_order_agg_month_platform WHERE `年度` = 2024 AND `月度` BETWEEN 1 AND 6 GROUP BY `平台` ORDER BY `平台`",
    },
    "W03-Q02": {
        "prompt": "汇总 yuhu.IDM_登录与接入日志 在 2025-07-01 至 2025-07-08 左闭右开期间的数据。依次返回 DATE(操作时间) AS 操作日期、日志标题、COUNT(*) AS 日志数量，按操作日期、日志标题升序。",
        "answer_sql": "SELECT DATE(`操作时间`) AS `操作日期`, `日志标题`, COUNT(*) AS `日志数量` FROM yuhu.IDM_登录与接入日志 WHERE `操作时间` >= '2025-07-01 00:00:00' AND `操作时间` < '2025-07-08 00:00:00' GROUP BY DATE(`操作时间`), `日志标题` ORDER BY `操作日期`, `日志标题`",
    },
    "W03-Q03": {
        "prompt": "对 soho.soho_ub_order_agg 中 order_key<'001' 的审计样本按平台汇总。依次返回 platform、COUNT(*) AS order_count、ROUND(SUM(order_amount),2) AS order_amount、ROUND(SUM(product_quantity),4) AS product_quantity，按 platform 升序。",
        "answer_sql": "SELECT platform, COUNT(*) AS order_count, ROUND(SUM(order_amount), 2) AS order_amount, ROUND(SUM(product_quantity), 4) AS product_quantity FROM soho.soho_ub_order_agg WHERE order_key < '001' GROUP BY platform ORDER BY platform",
    },
    "W04-Q01": {
        "prompt": "使用 EXPLAIN 检查 IMC 凭证明细查询：查询2024年第12期的日期、凭证字、凭证号、科目编码，按日期、凭证字、凭证号、科目编码升序并限制200行。",
        "answer_sql": "EXPLAIN SELECT `日期`, `凭证字`, `凭证号`, `科目编码` FROM imc.imc_voucher WHERE `会计年度` = 2024 AND `期间` = 12 ORDER BY `日期`, `凭证字`, `凭证号`, `科目编码` LIMIT 200",
    },
    "W04-Q02": {
        "prompt": "使用 EXPLAIN 检查 YUHU 日志查询：操作时间在 2025-07-01 至 2025-07-02 左闭右开，返回 id、操作时间、操作用户，按 id 升序并限制200行。",
        "answer_sql": "EXPLAIN SELECT id, `操作时间`, `操作用户` FROM yuhu.IDM_登录与接入日志 WHERE `操作时间` >= '2025-07-01 00:00:00' AND `操作时间` < '2025-07-02 00:00:00' ORDER BY id LIMIT 200",
    },
    "W04-Q03": {
        "prompt": "使用 EXPLAIN 检查 SOHO 订单查询：month_key='2025-06' 且 platform='天猫'，返回 order_key、order_time、order_amount，按 order_key 升序并限制200行。",
        "answer_sql": "EXPLAIN SELECT order_key, order_time, order_amount FROM soho.soho_ub_order_agg WHERE month_key = '2025-06' AND platform = '天猫' ORDER BY order_key LIMIT 200",
    },
    "W05-Q01": {
        "prompt": "查询 imc.dws_order_agg_month_platform 中2025年1月数据。依次返回年度、月度、平台、订单数量、销售金额、客户数量，按平台升序并写明LIMIT 1000。",
        "answer_sql": "SELECT `年度`, `月度`, `平台`, `订单数量`, `销售金额`, `客户数量` FROM imc.dws_order_agg_month_platform WHERE `年度` = 2025 AND `月度` = 1 ORDER BY `平台` LIMIT 1000",
    },
    "W06-Q01": {
        "prompt": "在一行中返回三个基础核对数：IMC 2025年1月平台汇总行数 AS imc_rows；YUHU id在1至1000之间的日志行数 AS yuhu_rows；SOHO order_key<'001'的订单行数 AS soho_rows。字段顺序必须一致。",
        "answer_sql": "SELECT (SELECT COUNT(*) FROM imc.dws_order_agg_month_platform WHERE `年度` = 2025 AND `月度` = 1) AS imc_rows, (SELECT COUNT(*) FROM yuhu.IDM_登录与接入日志 WHERE id BETWEEN 1 AND 1000) AS yuhu_rows, (SELECT COUNT(*) FROM soho.soho_ub_order_agg WHERE order_key < '001') AS soho_rows",
    },
    "W06-Q02": {
        "prompt": "使用 UNION ALL 汇总三个项目的固定范围记录数，返回 project、record_count：IMC为2025年1月平台汇总；SOHO为month_key='2025-06'；YUHU为2025-07-01整日。最后按 project 升序。",
        "answer_sql": "SELECT 'IMC' AS project, COUNT(*) AS record_count FROM imc.dws_order_agg_month_platform WHERE `年度` = 2025 AND `月度` = 1 UNION ALL SELECT 'SOHO' AS project, COUNT(*) AS record_count FROM soho.soho_ub_order_agg WHERE month_key = '2025-06' UNION ALL SELECT 'YUHU' AS project, COUNT(*) AS record_count FROM yuhu.IDM_登录与接入日志 WHERE `操作时间` >= '2025-07-01 00:00:00' AND `操作时间` < '2025-07-02 00:00:00' ORDER BY project",
        "rules": {"required_keywords": []},
    },
    "W06-Q03": {
        "prompt": "从 soho.soho_ub_order_agg 的 order_key<'010'样本中下钻 payment_lag_minutes>60 的订单。依次返回 order_key、order_id、order_time、platform、shop_name、payment_lag_minutes、order_status，按 payment_lag_minutes 降序、order_key 升序并限制200行。",
        "answer_sql": "SELECT order_key, order_id, order_time, platform, shop_name, payment_lag_minutes, order_status FROM soho.soho_ub_order_agg WHERE order_key < '010' AND payment_lag_minutes > 60 ORDER BY payment_lag_minutes DESC, order_key LIMIT 200",
    },
}


for question in QUESTIONS:
    exact = EXACT_SQL_ANSWERS.get(question["code"])
    if exact is None:
        continue
    question["prompt"] = exact["prompt"]
    question["rules"].update({
        "answer_sql": exact["answer_sql"],
        "exact_result": True,
        "query_enabled": True,
        "default_limit": 1000,
    })
    question["rules"].update(exact.get("rules", {}))
