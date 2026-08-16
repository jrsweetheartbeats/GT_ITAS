# GT_ITAS

IT 审计全流程管理系统，包含项目管理、底稿与附件、复核质控、自动填写预览，以及 SQL 与数据库六周学习刷题模块。

## 安全配置

仓库不包含数据库密码、API Key、客户底稿、复核输出或生产规则。复制 `.env.example` 并在部署环境填写真实值，运行前执行 `set -a; source .env; set +a`；`.env` 已被 Git 忽略。

首次初始化必须设置：

```bash
export AUDIT_FLOW_DB_HOST="数据库主机"
export AUDIT_FLOW_DB_USER="数据库账号"
export AUDIT_FLOW_DB_PASSWORD="数据库密码"
export AUDIT_FLOW_DB_NAME="ITA"
export AUDIT_FLOW_INITIAL_PASSWORD="首次管理员密码"
```

生产自动填写规则通过 `AUDIT_FLOW_AUTOFILL_RULES_PATH` 指向仓库外的私有 JSON；仓库内只提供空白示例。审计底稿模板放入本地 `templates/`，该目录不应存放客户已填写底稿。

## 安装与启动

```bash
python3 -m pip install -r requirements.txt
python3 -m alembic -c alembic.ini upgrade head
python3 -m audit_flow_system.main
```

系统仅支持 MariaDB。浏览器默认访问 `http://127.0.0.1:8010`。

详细说明见 [audit_flow_system/README.md](audit_flow_system/README.md)。
