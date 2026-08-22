# AI Test Navigator 迭代记录

## 2026-08-21 — M2.2 需求分析页体验升级（模型热切换 + 粘贴上传 + 流程轨道 + 结果重设计）

状态：完成（用户 8 点反馈逐项闭环）

后端：

- `dsh/runtime.py`：新增 `reconfigure(model, provider)` 运行时热切换（stop → 下次 run_turn 以新模型懒启动）+
  `AVAILABLE_MODELS` 注册表（v4-flash/chat/reasoner/coder）。
- `api/agents.py`：新增 `GET/POST /agents/runtime/config`（模型列表 + 热切换，非法模型 400 拒绝）。

前端（`requirements.tsx` + `styles.css`）：

- 日期修复：`created_at` 实为 ISO `T` 分隔格式，旧 `slice(5,16)` 截出 `08-21T13:54:3` 乱码；
  新 `relTime()` 解析后显示相对时间（刚刚/X 分钟前/今天 HH:MM/昨天/MM-DD）。
- 新建会话：清空视图 + 聚焦输入框 + composer 边框闪烁 + toast 提示（原点击无反馈）。
- 模型热切换：引擎条内嵌模型下拉（4 模型，当前项 ✓），切换即调 config API，新任务生效。
- 附件粘贴/拖拽：textarea onPaste 捕获 clipboard 文件（图片缩略图预览）+ composer onDrop 拖拽区
  （drop-hint 蒙层），附件以 chips 展示可删除；文档类文件自动作需求文档，其余为附件。
  移除原"更多选项"里的两个 file input（入口收敛）。
- 全宽布局：`.content { max-width: 1280px }` 导致宽屏右侧大片空白；
  `.content:has(> .req-layout) { max-width: none }` 聊天页全宽（实测 1600 屏聊天区 1344px）。
- 流程轨道常驻：引擎条下方 8-Agent 横向轨道（图标+短名），实时状态（完成 ✓ 绿 / 执行中蓝脉冲 /
  失败 ✗ 红），任何时刻可见全局进度；欢迎页去重（不再重复展示流程 chips）。
- 结果面板 v2：统计卡行（需求/证据/链路/用例/裁决/高风险/待复核 大数字卡）+ segmented tabs +
  卡片式内容（需求卡：优先级+验收标准 chips；证据卡：路径:行号+符号徽章+代码片段；
  用例卡：五类型色标+步骤列表+预期高亮；三视角三栏卡）；替代旧表格堆砌。
- 完成横幅：任务终态显示"✓ 分析完成 + 产出统计 + 报告号 + 耗时"总览条。
- 终态任务打开自动滚到结果区（done-banner 定位），过程详情往上翻。

验证（Playwright 无头实测 1600×900）：

- 点击历史任务全链路：API 请求(task/activity SSE/analysis) → 8 Agent 卡片 → 完成横幅 →
  统计卡 6/35/6/21/6/3/4 直接可见（无需滚动）→ 用例 21 卡 5 类型色 → 模型下拉 4 项 →
  新建聚焦 TEXTAREA → 全程无 console 错误。
- 模型热切换 API：flash→reasoner→flash 均即时生效；非法模型 HTTP 400。

踩坑记录：

- browser_use 子代理的坐标点击对 React 合成事件不可靠（两次误报"点击无效"），
  Playwright locator click 稳定复现全通过；UI 验证优先 Playwright。
- `:has()` 选择器 Chrome 105+ 生效（getComputedStyle 实测 maxWidth=none），作为渐进增强可接受。

## 2026-08-21 — M2.1 需求分析页聊天式重构（Agent 活动实时流式输出）

状态：完成

后端（DSH 事件 → 聊天活动流）：

- `dsh/runtime.py`：`run_turn` 新增 `on_event` 实时回调（桥接 SDK `on_notification`，
  逐事件透传 `session.event`，回调异常不阻断回合）。
- `services/orchestrator.py`：
  - 任务级活动流 `_activity`（内存 buffer + seq 序号，线程安全）；`activity_items()` 内存优先，
    进程重启后从 `dsh_events` 表重建粗粒度时间线。
  - `_activity_handler`：DSH 原始事件 → 聊天活动（tool/call 工具调用+参数预览、
    assistant/message 模型文本、skill 调用）；Agent 生命周期 agent_start（含模型信息）/
    agent_end（含原始输出 preview）/result（阶段结论）三段式。
  - `_emit` 非 Agent 阶段同步推系统消息（received/rule-analysis/completed/failed）。
  - `_extract_json` 修复：裸 JSON 后尾随说明文字/多块 JSON 导致 find/rfind 拼接解析失败
    （现象：模型明明输出了合法 items 却判定"DSH 未参与"降级）。改用 `JSONDecoder.raw_decode`
    解析首个完整 JSON 值，兼容围栏/裸 JSON/尾随噪声/多块输出。
- `db/entities.py`：新增 `save_dsh_event`/`list_dsh_events`（dsh_events 表持久化 Agent 生命周期）。
- `api/requirements.py`：新增 `GET /requirements/tasks/{id}/activity` SSE 端点
  （先回放全部历史再增量推送，终态自动关闭）。

前端（`frontend/src/pages/requirements.tsx` 重写为聊天式）：

- 左侧任务侧栏（新建 + 历史列表，点击切换，运行中显示实时进度%）替代页面底部历史表。
- 主区聊天流：用户需求气泡 → 系统阶段 pill → 8 个 Agent 卡片（图标/名称/模型徽章/运行 spinner
  /完成 ✓ 结论/失败 ✗）→ 结构化结果面板（7 tab）。
- Agent 卡片实时流式展开：工具调用行（⚙ grep 参数预览）、模型思考文本、模型原始输出
  （可折叠）；完成后自动折叠只留结论，点击头部可再展开。
- 顶部引擎条：DSH 就绪徽章 + provider + **模型名** + node 载体 + 任务实时状态/进度/报告号。
- composer 底部输入：项目多选下拉（搜索/分支/chip）+ 更多选项折叠（工作区/分支/需求文档/附件）
  + Ctrl+Enter 发送；贴底自动跟随滚动（上翻则停止跟随）。
- SSE 消费 `/activity`（含历史回放，刷新/切任务可恢复时间线）+ 3s 轻量状态轮询兜底。

验证：

- 流式实测（task-48e9501ec9d3）：requirement-analyst 输出 6 条需求；project-scout 阶段 60 秒内
  实时流出 13 次工具调用（bash → glob → grep 逐步探索工作区）+ 3 段模型中文思考文本。
- 前端产物 18 项聊天 UI 特征检查全 PASS（182.4KB）。

踩坑记录：

- deepseek-v4-flash 输出风格不稳定：有时围栏 JSON、有时裸 JSON+尾随说明文字，
  JSON 提取必须用 raw_decode 级容错。
- PowerShell 内联 python 多行字符串会触发 ScriptBlock 解析错误，复杂请求构造落临时脚本。

## 2026-08-21 — M2 多 Agent 语义分析（8-Agent 流水线 + 全景结果 + 多 tab 前端）

状态：完成

编排层（`backend/app/services/orchestrator.py` 重写）：

- 8-Agent 语义分析流水线：规则分析保底（报告落盘）→ requirement-analyst（需求结构化）→
  project-scout（项目相关性）→ code-locator（代码证据，Agent 经 glob/grep/read 实查源码）→
  call-chain（调用链影响）→ impl-reviewer（逐条实现审查）→ test-designer（五类测试用例）→
  quality-judge（质量裁决，与实现审查结论合并）→ report-writer（dev/qa/product 三视角摘要）。
- 每 Agent 独立 DSH 会话（`{task_id}--{agent_id}`），防上下文串味；单阶段失败降级跳过，任务不失败；
  全阶段进度经内存版本号 + DB 双写，SSE 增量推送。
- 模型输出容错提取：```json 围栏 / 裸 JSON / 首尾噪声；report-writer 兼容包裹 views 键与裸 dict 两种输出。

数据层（`backend/app/db/entities.py` 扩展）：

- 新增 CRUD：save/list_code_evidence、save/list_impact_scopes、save/list_test_cases、
  save/list_assessments、save_report_views、save_agent_session/list_agent_sessions。
- assessments 表新增 risk 列（启动时 ALTER 迁移）；dashboard_stats 增加 evidence/test_cases/
  needs_review 表级 COUNT。
- fail_stale_tasks：服务启动清理僵尸任务（上次进程退出时 pending/running → failed/interrupted）。

API（`backend/app/api/requirements.py`）：

- 新增 `GET /requirements/tasks/{id}/analysis` 全景结果端点（任务+需求+证据+影响+用例+裁决+摘要+会话）。
- `backend/app/api/dashboard.py`：evidence/test_cases/needs_review 改为表统计（原硬编码 0，M2 修复）。

前端（`frontend/src/pages/requirements.tsx` 重写）：

- 分析结果 7 tab：需求条目（优先级徽章+验收标准）/ 代码证据（项目/路径/行号/符号/置信度）/
  影响范围（风险徽章+链路步骤）/ 测试用例（五类标签+步骤+预期）/ 裁决结论（风险+置信度+证据引用）/
  报告摘要（dev/qa/product 三视角）/ Agent 会话（8 Agent 执行记录）。

验证（`scripts/smoke-e2e.py`，8010 端口，全部通过）：

- 电商订单超时取消需求 → 任务零降级完成：3 条 P0 需求（各 5 条验收标准）、5 处真实代码证据
  （executeTimeoutReservationOrder:585 等含路径/行号/符号）、3 条影响链路、20 条五类测试用例、
  3 条裁决（needs_review 标记）、3 视角摘要、8 个 Agent 会话全 ok、报告 RPT-0ab0e20a1b。
- dashboard db 源统计正确（evidence/test_cases/needs_review 来自表 COUNT）；僵尸任务清理生效。
- 前端 dist 产物包含全部 7 tab（esbuild ascii 转义，`\uXXXX` 大写十六进制）。

踩坑记录：

- esbuild minify 默认 charset=ascii：中文全部转义为 `\uXXXX`（大写十六进制），校验产物需按大写匹配。
- PowerShell 内联 python 单行命令携带中文/反斜杠会被转义污染，复杂校验落临时脚本执行。

遗留（M3）：

- 报告中心人工复核流（needs_review 状态流转）；需求条目 ID 未强制 REQ-xxx 规范。

## 2026-08-20 — M1 需求分析域完整落地（DB 持久化 + 任务流 + 语义解析入库）

状态：完成

数据层（SQLAlchemy 因网络不可用未采用，自建轻量 DAL）：

- `backend/app/db/engine.py`（新增）：MySQL（pymysql）优先 / SQLite（标准库）降级；短连接、
  `?` 占位符统一方言转换、JSON 列 dumps/loads、init_schema 可重复执行。
- `backend/app/db/entities.py`（新增）：10 表 DDL 双方言（analysis_tasks/requirements/code_evidence/
  impact_scopes/test_cases/test_runs/assessments/reports/agent_sessions/dsh_events）+ repository
  CRUD + dashboard 聚合统计。
- `backend/app/core/config.py`：新增 database_url（AI_NAVIGATOR_DB 优先，DATABASE_URL 兜底，
  默认 mysql://root:root@127.0.0.1:3306/ai-navigator；sqlite:///xxx.db 一键降级）。
- `backend/app/main.py`：启动时 init_schema，失败告警不阻塞（库不可用不影响文件分析）。

任务流：

- `backend/app/services/orchestrator.py`（新增）：分析任务异步编排 — 规则分析（报告落盘+入库）→
  DSH requirement-analyst 语义解析（JSON 容错提取）→ 需求条目入库；进度内存版本号 + DB 双写；
  DSH 不可用自动降级规则解析结果，任务不失败。
- `backend/app/api/requirements.py`：新增 5 端点 — POST /requirements/tasks（创建，multipart）、
  GET /requirements/tasks（列表）、/{id}（详情）、/{id}/events（SSE 进度流）、
  /{id}/requirements（需求条目）。旧 /analyze 端点保留兼容。
- `backend/app/api/dashboard.py`：DB 为主数据源（任务统计/最近任务/14 天趋势），DB 不可用降级
  报告文件统计（页面不空白）。

前端：

- `frontend/src/pages/requirements.tsx`：重写为任务流 — 提交 → 进度条 + 事件时间线（SSE）→
  需求条目表（优先级徽章 + 验收标准）→ 历史任务列表（点击回看）。
- `frontend/src/pages/dashboard.tsx`：真实数据 — 任务/需求/进行中/已完成统计卡、14 天趋势条形图、
  最近任务表（10 秒自动刷新）、DSH 状态卡。

验证（全部通过）：

- `scripts/smoke-db.py`：MySQL 建表 + CRUD + JSON 往返 + 聚合；SQLite 降级全链路；JSON 提取容错。
- `scripts/smoke-e2e.py`：创建任务 → 规则分析 → DSH 语义解析 4 条需求（含验收标准/优先级）→
  MySQL 入库 → dashboard db 源统计正确。

## 2026-08-20 — DSH Runtime 满血组合（V2：子代理 + 工作流 + Skills + Claude Code 桥）

状态：完成

背景：确认「SDK 集成 vs fork 源码」路线 — SDK 只是 JSON-RPC 驱动，Runtime 内部即完整 DSH，
满血与否取决于 cordis.yml 插件组合，无需 fork（git pull + 重建载体即可吃上游新能力）。

变更：

- `config/cordis.yml`（新增）：平台满血 Runtime 组合，替代 SDK 内置最小组合。启用：
  原生子代理 spawn/fork、Claude Code 子代理（subagent_claude_code）、工作流引擎 + ralph 自主循环、
  Skills（平台 skills/ 目录）、fs 全套（读写 + glob/grep）、todo/jobs/ask_user、
  token-meter + compaction 长会话压缩。参考官方 CLI standard 预设 + acp-agent 示例。
- `scripts/build-dsh-node-carrier.mjs`：新增 EXTRA_WORKSPACE_PACKAGES / EXTRA_HOISTED_PACKAGES
  扩展段，把 dsh-subagent-claude-code（workspace 包）+ @anthropic-ai/claude-agent-sdk +
  @anthropic-ai/sdk 复制进载体闭包（生产 CLI 的可选 Bundle，SDK 闭包默认不含）。
- `backend/app/core/config.py`：新增 dsh_cordis（config/cordis.yml）与 dsh_skill_dirs
  （skills/ 目录，经 DSH_CUSTOM_SKILL_DIRS 环境变量注入 Runtime）。
- `backend/app/dsh/runtime.py`：DeepSeekHarness 传入 cordis 参数 + 注入 Skills 目录环境变量。
- `skills/*/SKILL.md`：补 YAML frontmatter（name/description/whenToUse）—
  skill-filesystem 要求 frontmatter 必填，缺失会被静默丢弃。
- `scripts/smoke-dsh.py`：升级为满血验证 — 从事件流扫描工具目录，断言 subagent/
  subagent_fork/subagent_claude_code/workflow/skill/todo_write/write/grep 全部就位。

决策记录：

- Codex 子代理未启用（包不在闭包、机器无 codex CLI），扩展方式已写入 build 脚本注释。
- Claude Code 子代理依赖机器 claude CLI（已确认在 PATH）；需两行挂载：provider 注册
  （subagent-claude-code 插件行，官方 cordis.patch.yml 同款）+ 工具行（tool-subagent provider: claude-code）。
- hooks-claude-code / hooks-codex 桥未挂载（分析场景暂无 hooks 需求）。
- tool-ask-user / command-compact 无法挂载：依赖 CLI host 服务（userQuestions / commands），
  SDK Runtime 场景不提供，挂载会启动失败。
- cordis.yml `!!js` 表达式不能含 `[]` 字面量（被 YAML 解析为对象导致 schema 校验失败），
  数组返回值用 `.split(';').filter(Boolean)` 写法。
- dsh-tool-subagent-report 不在 SDK 闭包（examples 场景专用），已加入构建脚本扩展清单。

验证结果（scripts/smoke-dsh.py，exit 0）：

- 工具目录（事件流扫描）全部就位：subagent / subagent_fork / subagent_claude_code /
  workflow / skill / todo_write / write / grep / ralph / list_agents / send_message /
  interrupt_agent / job_* / bash / read / edit / glob。
- 真实子代理调用链路：主 Agent 派生 subagent → 子代理执行 → 汇总答案（281 事件，completed）。
- Web API 端到端：Runtime 启动 → requirement-analyst 输出结构化需求 JSON（1454 事件，completed）。

## 2026-08-20 — M0 商用级架构重构（菜单化 + DSH Runtime 全链路）

状态：完成

架构重构（详细蓝图见 `C:\AppsAi\deepseek-harness\plans\ai-test-navigator\ARCHITECTURE.md`）：

- 后端模块化：`app/api/` 按菜单域拆分为 8 个路由模块（dashboard/requirements/projects/agents/testing/reports/evidence/settings），新增功能=新增域，互不干扰。
- 前端 React 菜单化：React 18 + TypeScript + esbuild，侧边栏 8 个菜单域 + hash 路由，替换原平铺页面；`scripts/setup-frontend-deps.mjs` 从 DSH 仓库离线装配依赖，`scripts/build-frontend.mjs` 构建。
- DSH Runtime 集成（核心竞争力）：`app/dsh/runtime.py` 长驻 Runtime 管理器，SDK 以源码方式集成（sys.path 注入 `python/sdk/src`，git pull 即升级）；Windows node 载体由 `scripts/build-dsh-node-carrier.mjs` 离线构建（356 包闭包，修复 pnpm hoisted junction ELOOP）。
- DSH 凭据链路：内置 cordis.yml 未挂载 credentials-local，后端解析 `~/.dsh/.credentials.yaml` 经子进程环境注入 DEEPSEEK_API_KEY（已验证官方端点可用）。
- Agent 注册表：`app/dsh/agents.py` 注册 8 个 FDE 分析 Agent（需求分析→…→报告），M0 支持试运行，M2 接入完整编排。
- 修复：config.py `PROJECT_ROOT` 层数错误导致前端托管/报告路径错位。

端到端验证（全部通过）：

- 8 个菜单域 API 全部 200；前端 `/`、`/assets/*` 托管正常。
- DSH Runtime：node 载体启动 → JSON-RPC 握手 → deepseek-v4-flash 回合 completed。
- Agent 试运行：`requirement-analyst` 对护照 OCR 需求输出结构化 JSON（REQ-001/002…含优先级与验收标准），2179 事件。
- 冒烟脚本：`scripts/smoke-dsh.py`。

## 2026-08-20 — 接口 URL 精确分析与流式进度

状态：完成

- 识别输入中的 HTTP/HTTPS URL，进入接口逻辑审查模式。
- 从 URL 提取 endpoint，例如 `modifyDeliveryType`。
- 优先精确定位 Facade、Service、Biz 和相关 Java 实现，不再把 `https`、`payful` 等无关词作为主要证据。
- 接口分析报告生成专用测试场景：参数校验、状态边界、幂等、权限和下游异常。
- 增加 `/api/analyze/stream` SSE 接口，页面对纯文字接口查询显示接收、定位、完成阶段。
- 已对 `baofu-exchange-center` 的 `modifyDeliveryType` 验证：找到 Facade、Service、Biz 三处精确证据。
- 示例报告：`reports/RPT-64edc29338.md`。

## 2026-08-20 — 多模态需求输入入口

状态：完成第一步，视觉解析待接入

- 页面不再要求必须上传需求文档。
- 支持直接输入需求文字。
- 支持上传单个需求文档。
- 支持多选图片和其他附件。
- API `/api/analyze` 支持 `text`、`requirement` 和 `attachments`。
- 文本类附件会合并进入分析；图片和二进制附件当前登记文件名、类型和大小，避免错误当作文本。
- 页面已验证文字输入和附件输入。

下一步：

- 增加附件安全存储和报告证据引用。
- 接入 OCR/视觉模型，将图片内容转成结构化需求。
- 支持 PDF/DOCX 文本提取。

## 2026-08-20 — 一键启动脚本

状态：完成

- 新增 `start.bat`，支持双击启动。
- 新增 `start.ps1`，负责 Python、依赖、端口检查和 FastAPI 启动。
- 新增 `stop.bat`，用于停止 8090 服务。
- 8090 已占用时复用现有服务并打开浏览器，不重复启动。
- 已验证 PowerShell 语法和已运行服务复用逻辑。

## 2026-08-20 — 本地数据库约定

状态：已记录，待正式接入

- 本地数据库统一使用 MySQL 数据库 `ai-navigator`。
- 默认连接参数：`127.0.0.1:3306`、用户 `root`、密码通过环境变量注入。
- 增加 `.env.example`、`plansea/DATABASE.md` 和 SQLAlchemy/Alembic/PyMySQL 依赖。
- 当前 CLI 文件报告不依赖数据库，数据库不可用时不阻塞基础分析。

## 2026-08-20 — Phase 1 MVP

状态：完成

完成内容：

- 建立 Python + FastAPI 后端基础结构。
- 建立 Pydantic 需求、证据、影响、测试和结论模型。
- 支持 Markdown 需求解析。
- 支持 Java、Vue、JavaScript 源码关键词证据扫描。
- 支持 Git commit 信息读取。
- 支持五类测试用例生成。
- 支持 JSON、Markdown、HTML 报告。
- 接入 FastAPI `/api/health` 和 `/api/analyze`。
- 增加 DSH 可选客户端和无 Key/无 Runtime 降级。
- 增加需求分析与影响分析 Skills。
- 使用护照 OCR 示例完成端到端运行。

验证结果：

- 报告：`reports/RPT-ea08576f2d.html`
- 需求项：6 条
- 代码证据：30 条
- 影响区域：3 个
- 测试用例：30 条
- FastAPI 健康接口验证通过

已知问题：

- HTML 报告仍是 MVP 样式，需要升级为真正的可视化报告。
- 当前还没有执行真实业务测试命令。
- 当前源码定位主要基于关键词和文件命中。
- Windows 原生环境不启用 DSH Runtime，后续在 WSL2/Linux 验证。

计划对齐：

- 已将 FDE 工程师能力图谱的 7 大模块、35 个能力点映射到 `plansea/PLAN.md`。
- 当前 MVP 主要覆盖业务诊断、场景建模、AI 方案设计、工程实现和试点推进的基础能力。
- 系统集成、评测治理、企业推广和反馈产品化已纳入后续路线图。

下一步：

1. 优化 HTML 报告视觉结构。
2. 增加安全的测试命令执行器。
3. 使用 `PROJECT_INDEX` 增强调用链和影响范围。
4. 增加 Java/Vue 结构索引。
