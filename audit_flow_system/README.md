# IT审计全流程管理系统

本目录是新的全流程系统 MVP，不覆盖原有项目进度管理系统，也不移动现有底稿复核脚本。

## 技术栈

- 后端：FastAPI + SQLAlchemy
- 默认数据库：MariaDB `ITAS`
- 前端：FastAPI 托管的单页 HTML
- 复核脚本接入：可调用当前目录上级的 `复核规则/run_project_rules.py`

## 数据库

系统只支持 MariaDB。启动时会连接 MariaDB，并自动执行 `CREATE DATABASE IF NOT EXISTS ITAS`；表结构必须通过 Alembic migration 建立和升级，应用启动和导入脚本不会自动建表。

```text
mariadb+pymysql://root:******@127.0.0.1:3306/ITAS?charset=utf8mb4
```

如果本机 MariaDB 连接信息不同，可通过环境变量配置：

```bash
export AUDIT_FLOW_DB_HOST=127.0.0.1
export AUDIT_FLOW_DB_PORT=3306
export AUDIT_FLOW_DB_USER=root
export AUDIT_FLOW_DB_PASSWORD='你的密码'
export AUDIT_FLOW_DB_NAME=ITAS
export AUDIT_FLOW_DB_POOL_SIZE=5
export AUDIT_FLOW_DB_MAX_OVERFLOW=10
export AUDIT_FLOW_DB_POOL_RECYCLE=26600
export AUDIT_FLOW_DB_CONNECT_TIMEOUT=10
export AUDIT_FLOW_DB_READ_TIMEOUT=30000
export AUDIT_FLOW_DB_WRITE_TIMEOUT=30000
```

也可以直接提供完整 SQLAlchemy URL：

```bash
export AUDIT_FLOW_DB_URL='mariadb+pymysql://user:password@127.0.0.1:3306/ITAS?charset=utf8mb4'
```

`AUDIT_FLOW_DB_URL` 必须使用 `mariadb+pymysql`。本目录中的 `audit_flow.db` 及 `audit_flow.db.bak_*` 是历史 SQLite 文件/备份，不再作为运行库；不要把它们用于启动或迁移验证。

首次部署或模型变更后，先执行 migration：

```bash
cd "/Users/lirui/PycharmProjects/PythonProject/啊_ITA工具/IT审计底稿自动化与复核"
python3 -m alembic upgrade head
python3 -m alembic current
```

确认 `alembic current` 输出当前 head 后再启动服务。

## 启动

```bash
cd "/Users/lirui/PycharmProjects/PythonProject/啊_ITA工具/IT审计底稿自动化与复核"
uvicorn audit_flow_system.app:app --host 127.0.0.1 --port 8010 --reload
```

也可以直接运行入口文件，适合 PyCharm 运行配置：

```bash
python3 -m audit_flow_system.main
```

若端口被占用，可指定端口：

```bash
AUDIT_FLOW_PORT=8011 python3 -m audit_flow_system.main
```

打开：

```text
http://127.0.0.1:8010
```

## 当前已覆盖模块

- 用户管理：用户、角色、默认复核角色
- 项目管理：项目基本信息、审计年度、被审计单位、项目根目录、以前年度项目
- 执行安排：保留任务、项目成员、负责人字段
- 企业对接：后端已提供项目联系人接口
- 底稿管理：底稿登记、以前年度底稿引用、底稿提交复核
- 附件管理：附件登记、统一索引号生成、索引重复校验
- 自动复核：内置基础规则，也可调用现有 `复核规则/run_project_rules.py`
- 复核流转：经理、高级经理、总监、合伙人、质控人员顺序复核
- 自动填写规则：基于已完成项目样本，按附件索引和附件名称生成 C22/B 类底稿填写建议

新建项目时“项目根目录”可以留空。系统会在 `项目文件/` 下按“年度_被审计单位_项目编号_项目ID”生成独立目录，并自动建立：

- `底稿/计划阶段`
- `底稿/执行阶段`
- `底稿/结束阶段`
- `资料管理`
- `复核记录`
- `项目报告`

项目创建事务会同时复制 14 份标准 IT 审计底稿、登记 V1 初始版本，并把项目名称、项目编号、被审计单位、审计年度、审计期间、编制人、复核人及底稿索引写入可识别的底稿表头和备忘录占位符。可以通过 `AUDIT_FLOW_PROJECTS_ROOT` 修改默认项目目录根路径。任何模板复制、主数据写入或数据库提交失败都会回滚本次项目记录和新生成文件。

## 核心项目监控

首页“项目监控”不再仅依赖 `Workpaper.status` 判断完成度，而是按当前文件和复核结果核算：

- 文件可用：系统登记的底稿路径能够读取；
- 编制完成：底稿页眉同时识别到编制人和编制日期；
- 复核完成：底稿页眉同时识别到复核人和复核日期；
- 整改回复：优先读取项目目录内最新的 IT 审计复核表；
- 复核确认：以复核表“确认复核问题已解决”字段为准，项目组回复不等于问题关闭。

交付准备度口径为：文件可用 25% + 编制签名 30% + 复核签名 25% + 问题关闭 20%。页面会单独列示路径失联、签名不完整、问题未回复和回复待确认等阻塞，不以综合百分比替代明细判断。

项目目录变更后，可以只刷新项目根目录和底稿路径，不登记附件：

```bash
python3 -m audit_flow_system.tools.sync_project_files \
  --project-id 项目ID \
  --search-root "/项目搜索根目录" \
  --workpapers-only
```

确认 dry-run 结果后再增加 `--apply`。执行写入前程序会在 `audit_flow_system/db_backups/` 保存项目、底稿和附件登记备份；该操作只更新 MariaDB 登记信息，不修改真实底稿。

## 自动填写规则库

规则文件：

```text
audit_flow_system/data/autofill_rules.json
```

当前包含：

- 13 个项目来源提示：艾姆诗、刀锋、海王、汇洁、九芝堂、科蓝、朗特、力合科创、丽臣、特力、维度、星际悦动、长亮
- 15 条 C22 规则：SA-3、SA-4c、SA-5、SA-7、SA-10、SA-11、SA-12、SA-14、PE-5、PE-6、PE-7、PE-8、PM-4e、PM-5、PM-6
- 9 条 B 类规则：B22A-4-1、B22A-4-2、B22A-4-3、B22A-4-4-1、B22A-4-4-2、B23-15、B60-2-1、B60-2-2、B60-2-3

接口：

```text
GET /api/autofill-rules
GET /api/projects/{project_id}/autofill-suggestions
POST /api/projects/{project_id}/autofill-plan
GET /api/autofill-runs?projectId={project_id}
GET /api/autofill-runs/{run_id}/items
POST /api/projects/{project_id}/attachments/scan
POST /api/projects/{project_id}/attachments/reconcile-references
```

匹配结果会返回规则编号、适用底稿/页签、目标字段定位方式、匹配到的附件、缺失的必要证据和建议填写内容。当前阶段只生成建议，不直接写入 Excel。

写入计划接口默认只预览：

```json
{"apply": false}
```

返回内容包括工作簿路径、页签、字段、目标单元格/区域、旧值、新值和状态。若传入：

```json
{"apply": true}
```

才会将可定位且可直接写入的 Excel 单元格写回文件。`B22A-4-1` 的 IT 概要已支持结构化计划：系统会根据附件名称识别用友 U8、SAP、ERP、商城、旺店通、OA、CRM、MES、WMS 等系统，并在模板中按系统块填列序号、应用程序/基础设施名称、功能描述、索引号、复杂因素“是/否”和备注。公式列如复杂性和对审计策略的影响不直接写入。

前端“底稿复核”页已提供自动填写操作流：可按全部/C22/B类筛选生成建议，先预览写入计划并查看 planned、changed、unchanged、skipped、blocked 汇总，再通过“确认写回”执行 `apply=true`。写入结果会按状态高亮显示，blocked 项不会写入文件。

每次生成预览或执行写回都会保存一条自动填写记录和对应计划明细，记录建议数量、底稿数量、计划数量、changed/blocked 等摘要，以及每个单元格/文档定位的旧值、新值、状态和说明，便于后续追溯。

附件索引页支持扫描项目根目录：先以 `dry_run=true` 预览将登记的附件、拟生成索引号和匹配底稿，再确认登记写入附件台账。扫描会跳过已登记文件路径，支持 xlsx/xlsm/docx/pdf/图片/csv/txt 等常见证据文件。

附件索引页也支持底稿引用勾稽：系统会读取项目底稿中的 Excel、Word、文本类文件，识别 `<索引号>` 或类似 `C22-1` 的附件引用，并与附件台账索引号匹配。先以 `dry_run=true` 预览匹配、缺失和异常读取结果，确认后会把匹配到的底稿编号回写到附件台账的“底稿引用”字段。

表格型字段如 `B22A-4-2` 的重大业务流程行也已支持结构化计划：系统会根据附件名称推断销售与收款、采购与付款、生产/存货与成本等流程，并返回逐单元格计划，例如 `A6:H7`。如果项目同时存在 C22 附件和 B 类准备附件，B22A-4-2 会优先使用非 C22 附件推断流程和系统范围，减少密码策略、备份日志等执行阶段附件污染准备底稿。

`B22A-4-3` 的了解 IT 环境已支持结构化计划：系统会根据 IT 环境调查表、系统清单、数据库/操作系统/服务器/网络/接口/流程等附件名称推断应用程序、基础设施、IT 流程和信息处理行，并在 `.xlsm` 模板中跨“应用程序、基础设施、流程、信息处理”页签生成逐单元格计划。该规则用于把 B22A-4-1、B22A-4-2 和 C22 的系统范围统一到 `B22A-4-3` 索引。

`B22A-4-4-1` 的 ITGC 了解矩阵也已支持结构化计划：系统会根据匹配附件推断 SA-3、SA-4c、SA-5、SA-7、SA-10、SA-11、SA-12、SA-14、PE-5、PE-6、PE-7、PM-4e、PM-5、PM-6 等控制编号，并在多个页签中按 `ITGC 编号` 定位对应行，逐单元格生成控制描述、设计和执行了解过程、是否存在控制问题、问题描述的填写计划。若某个控制编号在整个工作簿不存在，系统只返回一条真实缺失的 blocked 结果。

`B22A-4-4-2` 的 IT 一般控制职责分离分析已支持结构化计划：系统会根据管理员清单、权限清单、岗位职责、开发/运维/业务/财务等附件名称推断安全管理、技术维护、新系统实施三类职责分离角色，并填列人员角色、授权审批、权限配置、监督、设计开发、复核测试、实施上线、业务/财务职责、缺陷判断和说明。模板预留行不足时，系统会先填可复用行，并对超出的角色单独返回 blocked。

`B23-15` 的了解信息处理控制已支持结构化计划：系统会根据业务流程、ITAC、系统接口、系统报表、系统清单等附件名称推断销售与收款、采购与付款、生产/存货与成本、费用报销、资金收付、总账与财务报告等信息处理控制行，并填列控制类别、索引号、业务流程、财务报表项目、认定、潜在错报风险、控制数据、实际控制活动、自动/人工、预防/检查、频率和涉及应用程序。若模板在“填写说明”前预留行不足，预览会标明插入位置，`apply=true` 时会在说明区前插入行并保留说明区。

`B60-2-1` IT复杂性判断表已支持结构化计划：Excel 模板会按正文判断区填列是否适用 IT 审计，并在测试范围区按应用系统/基础设施填列编号、系统名称、涉及重大业务流程、复杂性和备注。Word 版本当前返回字段级预览，直接段落/表格写回仍作为后续扩展。

`B60-2-2` IT审计进场前通知表已支持结构化计划：系统会从项目主表、企业对接人和项目成员信息中提取项目编号、被审计单位、进离场时间、客户IT联系人、项目合伙人/经理、IT顾问和IT团队负责人，并根据匹配附件勾选 ITGC、ITAC、会计分录测试、LEAP 使用和测试范围描述。该规则兼容维度、海王、徐工汽车样本中的不同模板行号和合并单元格。

`B60-2-3` Word 计划备忘录已支持直接写回：系统会更新标题、目的段中的企业名称和截止日、备忘录日期、项目计划/审计执行时间安排、“姓名/职级”IT 专业人员表、重大业务流程/涉及系统表、信息处理控制表和应用系统/数据库/操作系统/数据中心/网络范围表。若某个 Word 模板缺少对应表格，系统只对该表返回 blocked，不影响其他可定位字段写回。

## 后续扩展重点

1. 将旧项目进度管理 MySQL 数据迁移到当前模型。
2. 把 `复核规则/项目修订规则` 中的项目规则包封装为可配置规则集。
3. 增加更多 B 类表格型字段的结构化行生成，例如 B60 访谈记录和其他 ITAC 支持表。
4. 扩展更多 Word 类准备底稿的段落和表格直接写入器。
5. 增加 Excel/Word 底稿内容级年度替换，而不仅是登记信息和文件名。
6. 增加认证、登录和操作审计日志。
