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

## 核心表

| 表 | 用途 | 状态 |
|---|---|---|
| `analysis_tasks` | 分析任务、状态、项目、分支、commit | ✅ M1 起使用 |
| `requirements` | 结构化需求项 | ✅ M1 起使用 |
| `code_evidence` | 文件、行号、符号和证据摘要（M3.2a 起含 `req_ref` 关联需求） | ✅ M2 起写入（code-locator） |
| `impact_scopes` | 项目、模块、接口、数据影响 | ✅ M2 起写入（call-chain） |
| `test_cases` | 测试用例与自动化引用 | ✅ M2 起写入（test-designer） |
| `test_runs` | 测试命令、退出码、耗时、状态 | ⏸ 已建表，M4 测试执行引擎写入 |
| `test_evidence` | 日志、响应、截图、快照 | ⏸ 未建（随 M4 评估是否并入 test_runs） |
| `assessments` | 实现判断、风险、置信度和复核状态 | ✅ M2 起写入（impl-reviewer + quality-judge） |
| `reports` | 报告版本与导出路径 | ✅ M1 起使用（M2 起含三视角摘要） |
| `agent_sessions` | Agent 会话执行记录 | ✅ M2 起写入 |
| `dsh_events` | Agent 生命周期事件（时间线回放） | ✅ M2.1 起写入 |
| `model_configs` | 模型供应商配置（多供应商 + 热切换） | ✅ M2.2 起使用（api_key 明文本地存储，企业化前须迁移，见 PLAN.md P1） |
| `conversations` | 用户多轮会话（每会话独立 DSH 路由会话） | ✅ M3.2a 起使用 |
| `chat_messages` | 会话消息流（user/assistant + intent + task_id 关联） | ✅ M3.2a 起使用 |
| `feedback_items` | 人工确认、误报、漏报和改进反馈 | ⏳ M3.2 人工复核流新建 |

## 当前状态

- ✅ 2026-08-27：`delete_conversation(conv_id)` + `delete_task(task_id)` 级联删除（M3.2c）——
  删会话连带删 chat_messages + 会话内全部任务 + 任务衍生七表（requirements/code_evidence/
  impact_scopes/test_cases/assessments/reports/agent_sessions/dsh_events）。表结构不变。
- ✅ 2026-08-26：13 张表可重复执行（原 11 表 + `conversations` + `chat_messages`，M3.2a 多轮会话）；
  `code_evidence` 新增 `req_ref` 列（启动时 ALTER 轻量迁移）。
- ✅ 2026-08-24：实际 11 张表已建齐并可重复执行（原 10 表 + `model_configs`）；
  `assessments` 含 `risk` / `gaps` 列（启动时 ALTER 轻量迁移）。
- 连接串经 `AI_NAVIGATOR_DB`（或 `DATABASE_URL`）环境变量注入，默认 `mysql://root:root@127.0.0.1:3306/ai-navigator`；
  设 `AI_NAVIGATOR_DB=sqlite:///dev.db` 即降级 SQLite（无需任何驱动依赖）。
- 因网络受限 SQLAlchemy/Alembic 不可安装，采用自建轻量 DAL（pymysql + sqlite3 标准库，
  `?` 占位符方言适配）。表规模固定、无复杂 ORM 需求，此方案可维护。
- 写入链路见 `services/orchestrator.py`（8-Agent 各阶段落库对应关系见 [`PLAN.md`](./PLAN.md) §0.2）；
  建表入口 `main.py` lifespan → `init_schema()`；启动时 `fail_stale_tasks()` 清理僵尸任务。
- 表清单真相源：`backend/app/db/entities.py` 顶部注释与 DDL（本文件与代码不一致时以代码为准）。
- ⚠️ 已知债务：`model_configs.api_key` 明文存储（仅本地开发可容忍；P1 安全治理项）；默认连接串含 root:root（经 AI_NAVIGATOR_DB 覆盖）。
