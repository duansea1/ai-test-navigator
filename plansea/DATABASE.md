# AI Test Navigator 数据库约定

## 本地开发数据库

用户已指定使用本地数据库：

```text
数据库类型：MySQL（默认假设）
主机：127.0.0.1
端口：3306
用户名：root
密码：root
数据库：ai-navigator
字符集：utf8mb4
```

连接串：

```text
mysql+pymysql://root:root@127.0.0.1:3306/ai-navigator?charset=utf8mb4
```

> 如果本地实际数据库不是 MySQL，或端口不是 3306，只需要修改 `DATABASE_URL`，业务代码不应写死连接参数。

## 使用规则

1. 数据库名称固定使用 `ai-navigator`。
2. 本地开发默认使用 `127.0.0.1`，不连接生产数据库。
3. 账号密码只通过环境变量或本地 `.env` 注入，不写入业务源码。
4. `.env` 不提交版本库；仓库只保留 `.env.example`。
5. 迁移脚本必须可重复执行，并记录 schema 版本。
6. 数据库不可用时，分析 CLI 仍应能生成文件报告；数据库是历史记录和服务化能力，不应阻塞基础分析。
7. 后续 FastAPI 服务接入数据库后，保存任务、需求项、代码证据、影响范围、测试用例、测试执行、报告和人工复核记录。

## 计划中的核心表

| 表 | 用途 |
|---|---|
| `analysis_tasks` | 分析任务、状态、项目、分支、commit |
| `requirements` | 结构化需求项 |
| `code_evidence` | 文件、行号、符号和证据摘要 |
| `impact_scopes` | 项目、模块、接口、数据影响 |
| `test_cases` | 测试用例与自动化引用 |
| `test_runs` | 测试命令、退出码、耗时、状态 |
| `test_evidence` | 日志、响应、截图、快照 |
| `assessments` | 实现判断、风险、置信度和复核状态 |
| `reports` | 报告版本与导出路径 |
| `feedback_items` | 人工确认、误报、漏报和改进反馈 |

## 当前状态

- ✅ 2026-08-20 M1 已接入：`backend/app/db/`（engine + entities），10 表建齐（可重复执行）。
- 连接串经 `AI_NAVIGATOR_DB`（或 `DATABASE_URL`）环境变量注入，默认 `mysql://root:root@127.0.0.1:3306/ai-navigator`；
  设 `AI_NAVIGATOR_DB=sqlite:///dev.db` 即降级 SQLite（无需任何驱动依赖）。
- 因网络受限 SQLAlchemy/Alembic 不可安装，采用自建轻量 DAL（pymysql + sqlite3 标准库，
  `?` 占位符方言适配）。表规模固定（10 张）、无复杂 ORM 需求，此方案可维护。
- analysis_tasks / requirements / reports / agent_sessions 已在 M1 使用；
  code_evidence / impact_scopes / test_cases / test_runs / assessments / dsh_events 待 M2/M3 写入。
- 任务/需求写入链路见 `services/orchestrator.py`；建表入口 `main.py` lifespan → `init_schema()`。
