# IT审计底稿自动化与复核

本目录统一管理 IT 审计底稿的自动填写、安全验证、自动复核、复核流转和交付资料。

## 当前入口

- 主应用：`audit_flow_system/`
- 自动填写规则：`audit_flow_system/data/autofill_rules.json`
- 复核规则：`复核规则/`
- 复核表通用模板：`复核表/模板/`
- 历史复核表样例：`复核表/历史样例/`
- 审计标准与底稿模板：`IT审计标准/`
- 独立辅助工具：`tools/standalone/`
- 复核运行输出：`outputs/review/`
- 历史运行结果：`archive/历史复核输出/`
- 旧版实现（仅用于追溯）：`legacy/`

## 启动

```bash
cd "/Users/lirui/PycharmProjects/PythonProject/啊_ITA工具/IT审计底稿自动化与复核"
python3 -m alembic -c alembic.ini current
python3 -m audit_flow_system.main
```

当前运行库仅支持 MariaDB。真实底稿默认只读；自动填写的写入/读回验证必须使用 `audit_flow_system/tmp/autofill_verification/` 下的测试副本。

## 规则边界

- B 类和 C22 的当前规则以 `audit_flow_system/data/autofill_rules.json` 为准，`legacy/` 中的 Excel 规则表与 DeepSeek 生成器不再是主入口。
- 当前规则库共 46 条：C22 31 条、B 类 9 条、C21/C21-1/C26/A27 6 条。C22 已覆盖标准测试页签；PE-8.1 作为图像化物理环境附表，由 PE-8 规则和人工复核共同处理。
- 自动填写先匹配必要证据，再生成字段/单元格计划；缺证据、缺定位或模板不一致时应返回 `blocked` / `skipped`，不猜测写入。
- 系统名称可从附件索引识别，但数据库、操作系统和部署信息必须以项目系统清单/IT环境调查表为准，不按产品名称推测。
- 复核规则是筛查和质量控制辅助；正式问题必须包含可追溯的文件、页签、单元格/行号和证据。
