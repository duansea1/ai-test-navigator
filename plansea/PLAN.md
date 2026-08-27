# AI Test Navigator 总体计划

> 项目路径：`C:\Akua\ai-test-navigator`
>
> 目标：输入需求文档与测试环境源码，自动识别需求实现情况、代码证据、影响范围、验证范围和测试结果，输出可追溯的可视化质量报告。
>
> 最后更新：2026-08-24（计划校准：状态同步至 M3.0，锁定产品核心，重排后续路线）
>
> 当前阶段：**M3.0 已完成**。核心链路（需求输入 → 意图识别 → 8-Agent 分析 → 证据/用例/裁决 → 三视角报告）已在核心入口全链路可用。
>
> 能力图谱基线：[`FDE_CAPABILITY_MAP.md`](./FDE_CAPABILITY_MAP.md)。交付真相源（迭代记录）：[`CHANGELOG.md`](./CHANGELOG.md)。

---

## 0. 产品核心（不可变，2026-08-24 用户确认）

### 0.1 核心入口

**唯一核心入口：`http://localhost:8090/#/requirements`（需求分析页，聊天式工作台）。**

主链路：

```text
粘贴需求文字 / 接口 URL / 文档附件
  → 意图识别（intent-classifier：问答 / 需求分析 / 全流程）
  → 问答直接回答（qa-assistant）或进入 8-Agent 分析流水线
  → 实时 Agent 活动流（SSE：工具调用 / 模型思考 / 阶段结论）
  → 结构化结果面板（需求 / 证据 / 链路 / 用例 / 裁决 / 三视角）
  → HTML / JSON / Markdown 报告
```

一句话定位：帮助研发团队回答——这项需求是否真的实现、影响了什么、该验证什么、哪些结论可信、谁需要复核。

其余菜单域（工作台 / 项目管理 / Agent 编排 / 测试中心 / 报告中心 / 证据中心 / 系统设置）均为该主链路的支撑或展示面，不另立产品线。

### 0.2 核心资产：8-Agent 流水线（各阶段角色与能力）

Agent 定义于 `backend/app/dsh/agents.py`，编排在 `backend/app/services/orchestrator.py`：
每个 Agent 独立 DSH 会话（`{task_id}--{agent_id}`，防上下文串味）；单阶段失败降级跳过，任务不失败；DSH 不可用时整链降级规则分析（`services/analyzer.py` 阶段 0 保底）。各阶段输出统一经 `services/agent_validation.py` 强校验（REQ-xxx 强制 / 枚举收敛 / fail 必须有证据 / 修复丢弃计数进活动流）后才入库——不合法结论拒绝入库是本表输出契约的执行层（M2.3）。

| # | Agent ID | 角色 | 阶段能力 | 输出契约 | 落库 |
|---|---|---|---|---|---|
| 0 | intent-classifier | 意图识别 | 判断输入属于 问答 / 需求分析 / 全流程 | IntentResult | —（仅路由） |
| 0' | qa-assistant | 问答助手 | 工具能力 / 测试方法论问答 | Answer | — |
| 1 | requirement-analyst | 需求分析 | 需求拆结构化条目：角色、规则、输入输出、验收标准 | RequirementItem[] | requirements |
| 2 | project-scout | 项目侦察 | 项目相关性判断，确认分支 / commit / 扫描范围 | ProjectRelevance[] | 内存（供后续阶段） |
| 3 | code-locator | 代码定位 | 经 glob/grep/read 实查源码，定位 Controller/Service/Biz/Mapper 入口 | CodeEvidence[] | code_evidence |
| 4 | call-chain | 调用链 | 前端→网关→服务→数据库跨项目调用关系与影响范围 | CallChain[] | impact_scopes |
| 5 | impl-reviewer | 实现审查 | 逐条需求-实现比对，判定实现状态与缺口 | RequirementAssessment[] | assessments（与 7 合并） |
| 6 | test-designer | 测试设计 | 正常 / 异常 / 边界 / 幂等 / 权限五类用例 | TestCase[] | test_cases |
| 7 | quality-judge | 质量裁决 | 证据归因 → 风险等级 + 上线建议 | QualityVerdict[] | assessments |
| 8 | report-writer | 报告 | 研发 / 测试 / 产品三视角结论摘要 | ReportViews | reports |

### 0.3 DSH 融合策略（基于 / 二开，不从零开发）

Agent Runtime 层**不自研**。推理、工具、子代理、工作流、长会话等能力全部来自 DeepSeek Harness（DSH），平台只做编排与领域适配：

1. **源码集成**：DSH Python SDK 以 sys.path 源码注入（`python/sdk/src` + `sdk-runtime/src`），上游 `git pull` 即升级，无需 pip。
2. **满血组合**：`config/cordis.yml` 挂载插件组合——原生子代理（spawn/fork）、Claude Code 子代理桥、workflow + ralph 自主循环、Skills、fs 全套（glob/grep/read/write）、todo/jobs、token-meter + compaction 长会话压缩。
3. **Windows node 载体**：`scripts/build-dsh-node-carrier.mjs` 离线构建 356 包闭包。
4. **凭据链路**：后端解析 `~/.dsh/.credentials.yaml`，经子进程环境注入（密钥不落配置文件）。
5. **模型治理**：`model_configs` 表多供应商管理 + 运行时热切换（M2.2，切换即对新任务生效）。
6. **平台 Skills**：`skills/` 目录经 `DSH_CUSTOM_SKILL_DIRS` 注入，分析标准沉淀为 Skill 而非硬编码。

**工具平台雷达（每次迭代例行）**：先查 DSH 上游是否有新插件 / 新模型 / 新能力 → cordis 挂载 + `scripts/smoke-dsh.py` 验证 → 平台编排接入；只有上游确实没有时才评估自研。

### 0.4 核心原则（不变）

1. **证据优先**：每个判断关联文件、行号、符号、命令输出或测试证据。
2. **不确定性显式化**：没有找到证据时标记 `needs_review`，不直接当成缺陷。
3. **规则与 AI 分工**：程序负责扫描、执行、采集、存储；AI 负责语义理解、推理和解释。
4. **默认只读**：默认不修改业务源码、不推送、不切换工作区分支。
5. **测试环境基线**：涉及测试环境代码时，默认使用 `integration` 分支。
6. **安全降级**：没有 DSH Runtime 或 API Key 时仍能运行本地规则分析。

### 0.5 范围裁决（2026-08-24）

- **核心不变**：核心入口 `/#/requirements` + 8-Agent 各阶段角色与能力。
- **超出核心的不管**：企业集成（CRM / ERP / 工单 / IM / SSO / GitLab MR / CI 门禁）、多租户权限、评测集规模化等记为扩展项，**不排期**；FDE 图谱模块 05 整体搁置（标记 ⏸）。
- 与能力图谱的关系：图谱仍是长期范围基线，但执行顺序以本计划核心为准；搁置项见 [`FDE_CAPABILITY_MAP.md`](./FDE_CAPABILITY_MAP.md) 检查清单标记。

---

## 1. 里程碑状态（截至 2026-08-24）

交付细节以 [`CHANGELOG.md`](./CHANGELOG.md) 为准，本表只做索引：

| 里程碑 | 交付 | 状态 |
|---|---|---|
| Phase 1 MVP | 规则分析 + 三格式报告 + FastAPI | ✅ 完成 |
| M0 | 商用级架构重构：8 菜单域 + DSH Runtime 全链路 + React 前端 | ✅ 完成 |
| M1 | DB 持久化（11 表）+ 异步任务流 + SSE 进度 | ✅ 完成 |
| M2 | 8-Agent 语义分析流水线 + 全景结果 + 多 tab 前端 | ✅ 完成 |
| M2.1 | 聊天式重构：Agent 活动实时流式输出（/activity SSE） | ✅ 完成 |
| M2.2 | 需求分析页体验升级：模型热切换 / 粘贴拖拽 / 流程轨道 / 结果面板 v2 | ✅ 完成 |
| M2.3 | Agent 输出强校验层：REQ-xxx 强制 / 枚举收敛 / fail 必须有证据 / ValidationReport | ✅ 完成 |
| M3.0 | 全局交互升级：Ctrl+K 命令面板 / 可折叠侧栏 / 全局 Toast / Dashboard 可视化 / 空状态 | ✅ 完成（浏览器人工验收待做） |
| M3.1 | 核心体验收尾：命令面板最近任务 / 三中心空状态 / y 轴刻度 / 技术债清理 / 4 处文案修正 | ✅ 完成（构建与浏览器验收待补） |
| M3.2a | Agent 能力优化 + 多轮会话：10 Agent prompt 收紧 + 3 Skill 补齐 + call-chain steps 修复 + conversations/chat_messages（13 表）+ 校验失败重问 + 证据关联需求 | ✅ 完成（冒烟 108/0 通过；构建与浏览器待补） |
| M3.2b | Agent 子代理赋能：每个流水线 Agent 升级为该阶段「主理」（对契约输出全权负责），能力不足时按 fork（同质并行/交叉验证）/ spawn（异质分治）委派再合成；新建 agent-collaboration 共享 Skill；路由层 2 Agent 轻量不委派 | ✅ 完成（冒烟 108/0 通过；DSH 真实委派待浏览器验收） |
| M3.2c | 会话删除 + 路由 Agent 会话隔离修复：delete_conversation 级联删消息/任务/衍生七表 + DELETE API + 前端 × 按钮二次确认；classify/qa_answer 按 Agent 分会话修复「模型未返回内容」 | ✅ 完成（冒烟 123/0 + esbuild + live /api/chat 实测） |

---

## 2. 路线图（校准后）

> 原 Phase 2-6 按「核心优先」重排为 M3.1 → M3.2 → M4 → M5；移出的项见 §3 P2 扩展项。

### M3.1 — 核心入口体验收尾（已完成 2026-08-25）

- 命令面板（Ctrl+K）接入「最近任务」快速打开。
- 报告中心 / 证据中心 / 测试中心空状态统一迁移 EmptyState。
- Dashboard 趋势图 y 轴自适应刻度。
- 清理 `requirements.tsx` 的 `toastUnused` 占位与未使用 import。
- 修正过期文案 4 处（报告中心 / 证据中心 / 项目管理页 / README）。

验收：esbuild 构建通过 + 8090 浏览器验收（Ctrl+K 打开最近任务、各中心空状态、趋势图刻度）。⚠️ 本轮分类器故障构建未跑，待补。

### M3.2 — 人工复核流（「不确定性显式化」的闭环）

- `needs_review` 结论状态流转 API（确认 / 误报 / 漏报）+ 报告中心操作入口。
- 需求条目 ID 强制 `REQ-xxx` 规范（入库前校验）。
- 人工复核结论写入 `feedback_items` 表（新建）。
- 复核时固化轻量快照（需求输入、模型、commit）与复核人 / 时间留痕（审计基础）；复核结论沉淀为后续评测样本。

验收：一条 needs_review 结论可在页面上被人工确认并留痕；复核数据可查询。

### M4 — 测试执行引擎（核心版）

- 白名单命令 + dry-run 先行；默认只读，禁止生产环境连接。
- `test_runs` 表真实写入（命令 / 退出码 / 耗时 / 日志摘要）。
- 测试失败自动归因到需求条目。
- 首个支持目标从 Maven 单测 / pytest 二选一（以真实试点项目为准）。

验收：护照 OCR 或 customer 登录示例至少一条真实测试命令执行、入库并归因。

### M5 — 证据深度（核心版）

- `PROJECT_INDEX` 作为 code-locator / call-chain 的知识源输入（FDE 能力点：RAG 设计）。
- 调用链 Mermaid 可视化（结果面板 + HTML 报告）。
- 证据中心从占位页升级为真实代码证据检索。

验收：护照 OCR 示例识别跨项目链路（商户端 → international-core → customer-core → admin-core → 运营后台），并区分「未找到」与「证据不足」。

### M6+ — 扩展项（不排期）

见 §3 P2。触发条件：核心链路稳定 + 用户明确提出。

---

## 3. 未完成清单

### P0（下一迭代：M3.2）

- [x] 命令面板接入最近任务（M3.1 完成）
- [x] 各中心空状态统一 EmptyState（M3.1 完成：报告/证据/测试中心）
- [x] Dashboard 趋势图 y 轴自适应刻度（M3.1 完成）
- [x] 清理 requirements.tsx 技术债（toastUnused / 未用 import）（M3.1 完成）
- [x] 报告中心过期文案修正（M3.1 完成，共 4 处：报告/证据/项目页 + README）
- [x] 多轮会话（M3.2a 完成：conversations/chat_messages 13 表 + 会话级 DSH 路由 + /api/chat 对话回合 + 前端线程化）
- [x] Agent prompt 契约收紧 + 3 个空 Skill 补齐（M3.2a 完成）
- [x] call-chain steps 校验修复 + code-locator 证据关联需求（M3.2a 完成：req_ref 列 + 归并）
- [x] Agent 子代理赋能（M3.2b 完成：8 流水线 Agent 升级主理 + fork/spawn 委派再合成 + agent-collaboration Skill + 路由层轻量不委派；冒烟 [15] 108/0）
- [ ] needs_review 人工复核流（状态流转 + 报告中心 UI + feedback_items 表）
- [ ] 需求条目 ID 强制 REQ-xxx 规范（M2.3 校验层已强制；入库路径兜底见 M3.2 验收）
- [ ] M3.0/M3.1/M3.2a/M3.2b 浏览器人工验收（Ctrl+K 最近任务 / Ctrl+B / Toast / 趋势图刻度 / 意图徽章 reason / 多轮对话连续性 / 子代理委派活动流）
- [x] 补跑 `python scripts/smoke-agents.py`（M2.3 + 路由 [10][11] + M3.2a [12][13][14] + M3.2b [15]，108 PASS / 0 FAIL）
- [ ] 补跑前端构建 `cd frontend && node ../scripts/build-frontend.mjs`（M3.1 + M3.2a 会话流）
- [ ] 重启 8090 实测「你好」→ 追问「帮我分析个登录需求」→ 问答追问：验证会话连续性与模型真实被调

### P1（核心增强：M4 / M5）

- [ ] 测试执行引擎：白名单 + dry-run + test_runs 入库 + 失败归因
- [ ] PROJECT_INDEX 知识源接入（code-locator / call-chain 上下文）
- [ ] Mermaid 调用链可视化
- [ ] 证据中心真实检索页（替换占位）
- [x] Agent 输出强校验（M2.3 已落地：`services/agent_validation.py` — REQ-xxx 强制 / 枚举收敛 + 中文别名 / confidence 钳制 / fail 必须有证据 / ValidationReport 进活动流；冒烟 `scripts/smoke-agents.py`）
- [ ] 评测基线：护照 OCR + customer 登录 golden case 标注与回归脚本（复核结论沉淀为样本）
- [ ] 安全治理迁移：`model_configs.api_key` 明文改引用 / 加密 + 收紧默认 root:root 连接（企业化前置）
- [ ] `/api/analyze` 上传接口测试补齐（smoke-e2e 覆盖）

### P2（扩展项，不排期）

- [ ] OCR / 视觉需求输入（见 [`VISION_INPUT.md`](./VISION_INPUT.md) 路线 C：OCR 文本 + 原图证据 + 视觉模型）
- [ ] 评测集规模化与准确率 / 误报 / 漏报指标（golden case 基线见 P1）
- [ ] 路由兜底率监控埋点（降级次数/原因可查；M3.2 feedback_items 表落地时顺带设计）
- [ ] Memory 架构（对话上下文/用户偏好记忆；M4 后按真实使用痛点再议）
- [ ] Guardrails 独立护栏层（防注入/防泄露；当前内部输入源风险低）
- [ ] 任务取消 / 重试 / 队列化
- [ ] GitLab MR 自动分析 / CI 质量门禁
- [ ] 企业 IM / 工单 / SSO 集成
- [ ] 报告版本对比 / 历史趋势看板

---

## 4. 当前技术架构（实际）

```text
React 18 + TypeScript + esbuild（hash 路由，核心入口 /#/requirements）
                |
        HTTP API + SSE（FastAPI, :8090）
                |
   orchestrator.py（任务编排：规则保底 + 8-Agent 流水线）
                |
      +---------+----------+----------------+
      |         |          |                |
  DSH Runtime  规则分析器  轻量 DAL         报告生成器
  (cordis 满血  analyzer   MySQL/SQLite     JSON/MD/HTML
   子代理/工作流  .py       11 表           (reporter.py)
   /Skills)
```

代码目录：

```text
backend/app/api/         8 个菜单域路由（dashboard/requirements/projects/agents/testing/reports/evidence/settings）
backend/app/services/    orchestrator（编排）、analyzer（规则保底）、reporter（报告）
backend/app/dsh/         runtime.py（DSH 长驻管理）、agents.py（8+2 Agent 注册表）
backend/app/db/          engine + entities（双方言轻量 DAL）
frontend/src/            React 前端（esbuild 构建，非 Vite）
config/cordis.yml        DSH 满血插件组合
skills/                  可复用分析标准（经 DSH_CUSTOM_SKILL_DIRS 注入）
scripts/                 构建（build-frontend / build-dsh-node-carrier）+ 冒烟（smoke-dsh / smoke-db / smoke-e2e）
plansea/                 本计划、能力图谱、数据库约定、迭代记录
reports/                 生成的报告
requirements/            示例需求文档
```

---

## 5. 数据对象与状态

模型位于 `backend/app/models/schemas.py`：

```text
RequirementItem
  -> CodeEvidence
  -> ImpactScope
  -> TestCase
  -> RequirementAssessment
```

核心状态：

```text
ImplementationStatus: implemented / partially_implemented / not_found / uncertain
Verdict: pass / fail / blocked / needs_review
```

约束：

- `needs_review` 表示证据不足或尚未完成语义审查。
- `blocked` 只用于环境、依赖、权限或测试数据导致无法执行。
- `fail` 必须有可复验的代码或测试证据。

M2 起流水线各阶段结果直接落库（见 §0.2 表）；规则分析报告仍写文件（`reports/`）。表清单与状态见 [`DATABASE.md`](./DATABASE.md)。

---

## 6. 验收样板（真实需求）

| 样板 | 需求 | 状态 |
|---|---|---|
| 护照 OCR 链路 | `requirements/passport-ocr-demo.md`（商户端→international-core→customer-core→admin-core→运营后台） | Phase 1 验收通过；M5 用于跨项目链路验收 |
| customer 登录逻辑 | `scripts/req_customer_login.md`（LoginServiceImpl.checkPwd 五种登录方式、错误锁定、风险关注点） | M2 流水线实测完成（task-c0a8418fff04） |

新能力优先用这两个样板做端到端验收。

---

## 7. 每次迭代的完成定义

一次迭代只有同时满足以下条件，才标记为完成：

- 计划中的代码已落盘。
- 新增能力有至少一个自动化验证或可重复命令。
- 报告或 API 输出可被检查。
- 失败和阻塞原因已记录。
- `PLAN.md` / `CHANGELOG.md` 同步更新状态与下一步。
- 没有执行违反工作区规则的 git 上传或危险操作。

---

## 8. 当前运行命令

```powershell
# 一键启动（推荐）：双击 start.bat，或
cd C:\Akua\ai-test-navigator\scripts; powershell -File ..\start.ps1

# 手动启动 FastAPI（:8090）
cd C:\Akua\ai-test-navigator
$env:PYTHONPATH = "$PWD\backend"
uvicorn app.main:app --host 127.0.0.1 --port 8090

# 前端构建（React + esbuild）
cd frontend; node ../scripts/build-frontend.mjs

# 冒烟验证
python scripts/smoke-db.py       # DB 建表 + CRUD + SQLite 降级
python scripts/smoke-dsh.py      # DSH Runtime 满血组合
python scripts/smoke-e2e.py 8090 # 端到端：创建任务→8-Agent→入库→dashboard
```
