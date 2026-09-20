# ITAS 培养计划 JSON 协议

当前协议版本：`1.0`

JSON 由网页版 ChatGPT 根据员工调研、历史任务、Review 记录和项目安排生成；ITAS 只负责校验、预览、事务导入和后续执行跟踪。页面字段不是协议，协议版本才是长期接口。

## 顶层结构

```json
{
  "schemaVersion": "1.0",
  "employee": {},
  "plan": {},
  "weeks": [],
  "assessment": {}
}
```

正式 JSON Schema 位于：`audit_flow_system/data/training-plan.schema.json`。

TypeScript 类型位于：`audit_flow_system/static/js/types/training-plan.d.ts`。

## 字段规则

### employee

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | ITAS 中的员工简称或账号，例如 `CYX` |
| `name` | string | 员工姓名 |

`code` 必须能够在 ITAS 用户或已关联人员档案中解析。解析失败时，ITAS 不会导入。

### plan

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | string | 计划标题 |
| `type` | string | 例如 `special_training` |
| `period` | string | 例如 `month_01` |
| `startDate` / `endDate` | `YYYY-MM-DD` | 计划周期 |
| `overallGoal` | string | 总体目标 |
| `mentorCode` | string | Mentor 的 ITAS 用户账号或人员简称；没有导师时传空字符串 |

### weeks 与 tasks

每周包含 `weekNo`、目标、日期、预期交付物和任务列表。任务类型只能是：

`learning`、`quiz`、`practice`、`project`、`assignment`、`self_check`、`review`

任务的 `taskCode` 在同一计划内必须唯一，例如 `W1-01`。`prerequisiteTaskCodes` 必须引用同一计划中存在的其他任务，不能依赖自身。

任务日期必须位于所属培养周内；培养周日期不能明显超出培养计划周期。

任务还可以传入可选字段：

- `purpose`：为什么要学习该任务；未提供时 ITAS 使用 `description` 作为展示兜底。
- `selfCheckQuestions`：提交前题目数组。可传普通自检字符串，也可传 `choice` 选择题或 `fill_blank` 填空题；选择题至少提供两个 `options`，并通过 `answer` 配置标准答案。学员必须全部答对后才能通过每日任务。

### learningMaterials

材料类型只能是：

`itas_page`、`external_link`、`document`、`video`、`case`、`reference`

一个任务可以有多个材料。

每份材料还可指定可见定位：

- `courseScope: "common"`：通用课程，适合全体学员复用，例如 IT 审计基础、财务知识和 AI 日常应用。
- `courseScope: "personal"`：个人课程，仅为该员工当前培养任务、能力短板或项目安排配置。

为兼容已有 JSON，未传 `courseScope` 时按 `personal` 处理。通用课程也会随任务展示，但在任务详情中与个人课程分区，方便学员知道哪些内容是必须补齐的个人训练。

### submission

每个任务必须明确：

- 是否需要提交：`required`
- 提交类型：`submissionType`
- 提交标题：`title`
- 提交要求：`requirements`

ITAS 会把这些内容保存到任务上，实际提交记录另行保存并按版本递增，不覆盖历史版本。

### 学习闭环扩展

导入后的任务详情支持材料阅读记录、自检问题和版本化作业提交。学员可以调用：

```http
GET  /api/development/tasks/{taskId}
POST /api/development/tasks/{taskId}/materials/{materialId}/read
POST /api/development/tasks/{taskId}/submit
POST /api/development/tasks/{taskId}/submit-file
POST /api/development/submissions/{submissionId}/review
```

提交前必须完成 `selfCheckQuestions`；每次提交会自动递增 V1、V2、V3，不覆盖历史提交。导师 Review 通过后任务变为 `completed`，要求修改后变为 `needs_revision`。

### Blocker / 卡点

学员提交卡点前必须填写 `problem`、`confirmedFacts`、`materialsChecked`、`initialJudgment`、`attemptedSolutions`、`missingInformation` 和 `mentorQuestion`。提交后任务自动变为 `blocked`，卡点历史不会覆盖。

导师可使用：

```http
GET   /api/development/blockers/pending
GET   /api/development/blockers/{blockerId}
PATCH /api/development/blockers/{blockerId}/respond
```

`action=continue_self_processing` 会将任务恢复为 `in_progress`；`action=resolved` 也会恢复任务为 `in_progress`，同时保留解决人、解决时间、持续天数和导师回复。

### Mentor 工作台与月度评价

导师工作台接口：

```http
GET /api/development/mentor-workbench
GET /api/development/mentor/submissions/{submissionId}
GET /api/development/mentor/plans/{planId}/assessment
PUT /api/development/mentor/plans/{planId}/assessment
GET /api/development/mentor/plans/{planId}/assessment/export?format=json
GET /api/development/mentor/plans/{planId}/assessment/export?format=markdown
```

月度评价维度、权重和 thresholds 均读取导入计划配置。ITAS 计算加权总分并输出 `nextStageSuggestion`，不会自动创建下月培养计划。保存评价时会把当时的客观学习信号一并写入 `summary.objectiveEvidence`，供之后生成个人月度复核引用。

### 学习信号埋点

ITAS 从学员操作中沉淀两类客观数据，不替代 Mentor 判断：

- `development_learning_events`：课件打开、材料阅读、笔记、提交、完成学习、卡点、Review，以及预留的 `courseware_heartbeat` / `task_focus`
- `development_quiz_item_results`：每一题的对错历史，**答错被拦下的尝试也会落库**，并带 `knowledgeKey` / `skillTag`

选择题可在协议中传入可选字段 `topic`、`knowledgeKey`，便于跨任务汇总同一知识点。

```http
GET  /api/development/mentor/plans/{planId}/review-evidence
POST /api/development/tasks/{taskId}/signals
```

`review-evidence` 会按完成率、首过率、错题、卡点、Review 返工和能力标签给出 `reviewHints`，对应月度复盘里的 B 段能力变化；C/D 项目复盘仍需结合当月项目，系统只提供 `projectContextHints`。

### assessment

评分维度不固定，由 JSON 传入。每个维度包含：

- `code`
- `name`
- `weight`
- `description`

所有 `weight` 合计必须等于 `100`，`totalScore` 当前必须为 `100`。

评分阈值必须覆盖不重叠的分数区间，并提供 `nextAction`，例如：

```json
[
  {"min": 0, "max": 59, "nextAction": "continue_foundation"},
  {"min": 60, "max": 79, "nextAction": "advance_with_remediation"},
  {"min": 80, "max": 100, "nextAction": "advance_complexity"}
]
```

## 导入流程

### 1. 仅校验，不导入

```http
POST /api/development/import/validate
Content-Type: application/json
```

该接口检查 JSON Schema、日期、人员、任务编号、前置任务、评分权重和阈值，但不会写入数据库。

### 2. JSON Preview

```http
POST /api/development/import/preview
Content-Type: application/json
```

返回员工解析结果、周数、任务数、材料数、需提交任务数、评分维度和任务编号列表。

### 3. 确认导入

```http
POST /api/development/import/confirm
Content-Type: application/json
```

只有确认接口会写入数据库。导入在一个事务中完成，任何异常都会回滚。相同员工和相同 `period` 已存在计划时，ITAS 会拒绝导入，不覆盖原计划。

## 完整 Example JSON

```json
{
  "schemaVersion": "1.0",
  "employee": {
    "code": "CYX",
    "name": "陈亦浠"
  },
  "plan": {
    "title": "CYX 第1个月 IT审计基础训练",
    "type": "special_training",
    "period": "month_01",
    "startDate": "2026-09-01",
    "endDate": "2026-09-30",
    "overallGoal": "建立从业务流程、系统处理到审计证据和结论的完整链路，并能在Review下完成常规ITGC测试。",
    "mentorCode": "lirui"
  },
  "weeks": [
    {
      "weekNo": 1,
      "title": "财审到IT审计",
      "objective": "把熟悉的财审程序连接到系统、数据和IT审计证据。",
      "startDate": "2026-09-01",
      "endDate": "2026-09-07",
      "expectedDeliverable": "业务—系统—科目/认定映射表",
      "tasks": [
        {
          "taskCode": "W1-01",
          "title": "完成收入流程映射",
          "taskType": "practice",
          "description": "从订单、发货、开票、收入确认和回款识别系统及数据依赖。",
          "startDate": "2026-09-01",
          "dueDate": "2026-09-03",
          "estimatedHours": 3,
          "prerequisiteTaskCodes": [],
          "learningMaterials": [
            {
              "title": "IT审计基础能力培训",
              "type": "itas_page",
              "courseScope": "common",
              "url": "/static/training/01-IT审计基础能力培训.html",
              "description": "了解业务、系统、数据和审计目标之间的关系。"
            }
          ],
          "instructions": "标出每个业务步骤对应的应用系统、数据来源、科目、认定和IT控制。",
          "submission": {
            "required": true,
            "submissionType": "document",
            "title": "收入流程映射表",
            "requirements": "提交可编辑表格，并在备注中说明至少一个ITGC依赖。"
          },
          "completionCriteria": "覆盖至少5个业务步骤，且导师抽查3个步骤时能够口头解释。",
          "mentorReviewRequired": true
        }
      ]
    },
    {
      "weekNo": 2,
      "title": "ITGC从零设计",
      "objective": "能够围绕控制目标、风险、程序、证据和异常完成一个常规ITGC测试。",
      "startDate": "2026-09-08",
      "endDate": "2026-09-14",
      "expectedDeliverable": "用户访问管理ITGC底稿",
      "tasks": [
        {
          "taskCode": "W2-01",
          "title": "设计离职账号测试",
          "taskType": "assignment",
          "description": "针对离职账号停用及时性设计测试程序。",
          "startDate": "2026-09-08",
          "dueDate": "2026-09-12",
          "estimatedHours": 5,
          "prerequisiteTaskCodes": ["W1-01"],
          "learningMaterials": [
            {
              "title": "ITGC案例",
              "type": "case",
              "courseScope": "personal",
              "url": "",
              "description": "员工离职后仍可登录ERP的案例。"
            }
          ],
          "instructions": "写清控制目标、风险、测试程序、证据、异常、进一步程序和结论。",
          "submission": {
            "required": true,
            "submissionType": "workpaper",
            "title": "用户访问管理测试底稿",
            "requirements": "不得只写结论，必须保留样本范围、证据索引和异常判断依据。"
          },
          "completionCriteria": "在不给现成模板的情况下完成可Review底稿。",
          "mentorReviewRequired": true
        }
      ]
    }
  ],
  "assessment": {
    "dimensions": [
      {"code": "scope_finance", "name": "Scope与财审连接", "weight": 20, "description": "能否把IT范围连接到业务流程、科目和认定。"},
      {"code": "procedure_design", "name": "程序设计", "weight": 25, "description": "能否独立设计目标、风险、程序和证据要求。"},
      {"code": "exception_judgment", "name": "异常判断", "weight": 25, "description": "能否区分资料不足、个别例外和控制缺陷。"},
      {"code": "project_progress", "name": "项目推进", "weight": 15, "description": "能否按期交付并主动暴露卡点。"},
      {"code": "expression_retro", "name": "表达与复盘", "weight": 15, "description": "能否清楚说明事实、判断、缺口和下一步。"}
    ],
    "totalScore": 100,
    "thresholds": [
      {"min": 0, "max": 59, "nextAction": "continue_foundation"},
      {"min": 60, "max": 79, "nextAction": "advance_with_remediation"},
      {"min": 80, "max": 100, "nextAction": "advance_complexity"}
    ]
  }
}
```
