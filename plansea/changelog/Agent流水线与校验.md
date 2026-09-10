# Agent流水线与校验

## 2026-09-01 — M3.4.1 输入保真 + M3.5 Agent 间上下文传递修复（输入+输出全流程优化）

状态：**完成**（冒烟 155/0 + live 端到端闭环实测）

> 用户要求：「继续优化我们的agent…还是优化 输入+输出 整个流程的」。上半场修输入失真（M3.4.1），下半场修 Agent 间上下文传递与输出侧记忆闭环（M3.5）。

### 一、M3.4.1 输入保真（chat/stream 丢附件——上轮误报通过的严重 bug）

- **根因**：`/api/chat/stream` 签名没有 `attachments` 参数——前端 M3.4 起全量走流式端点，FormData 里的附件字段被 FastAPI 静默丢弃。上轮 live 冒烟场景 3「通过」是误判（模型收到空输入回了自我介绍）。
- **修复**：`_merge_text_attachments()` 共享函数（/api/chat 与 /api/chat/stream 统一）：文本附件内容并入提问（单附件截 4000）；纯图片 → 终帧 intent=analyze；文字+图片混合 → 尾注「另有 N 个图片/二进制附件，文本模型无法读取其内容」。
- **前端**：删 `hasBinary` 本地扩展名拦截（与后端 _TEXT_SUFFIXES 双头维护易漂移），附件统一进 stream 由后端裁决。
- 冒烟 [19] 节 7 断言；live 场景扩到 7（新增纯图片→analyze、文本附件经 stream 命中附件内容）。

### 二、M3.5 Agent 间上下文传递修复（digest 失真三处）

1. **`_requirement_digest` 静默丢需求**：limit=12 截断时第 13+ 条需求下游 Agent 完全不可见（证据/用例/裁决对它们永远不生成）。修复：超限显式注明「另有 N 条需求未列出，ID 从 REQ-0XX 起」。
2. **`_evidence_digest` 不带代码原文**：只给 path:line+symbol，审查 Agent 拿不到 snippet（库里存着最多 4000 字）只能凭位置猜结论。修复：每条带 160 字代码摘录 + 超限注明。
3. **三个 Agent 缺上游产物输入**：
   - `call-chain`：prompt 要求「只输出有代码证据支撑的链路」却从不给它证据 → 现在传入 code-locator 证据 digest；
   - `test-designer`：不拿 impl-reviewer 审查结论（高风险缺口是用例重点来源）→ 现在传入审查结论摘要（缺口置顶）；
   - `quality-judge`：不拿已生成用例（裁决要答「该测的测全没」）→ 现在传入用例概览（30 条内）。

### 三、输出侧记忆闭环：任务结论回写会话（M3.5 核心新增）

- **根因**：会话里只有「已创建任务执行中」，任务完成后追问「刚才结论如何」，历史注入里没有结论，问答 Agent 答不上。
- **修复**：`entities.find_conversation_of_task()`（chat_messages.task_id 反查）+ `orchestrator._notify_conversation()` 在 4 个终态分支（完成/仅分析完成/无需求/失败）回写带 task_id 的 assistant 消息（含统计 + 高风险/待复核数）——会话流渲染为可点击任务块，`_history_block` 注入让问答接上任务话题。
- **前端**：`finish()` 空闲时刷新会话消息（streamingRef 防打断流式气泡），「分析任务完成」任务块实时出现在当前会话。

### 四、路由韧性：瞬时故障退避 + 启发式问句特征放宽

- **实测踩坑**：任务流水线刚跑完时 node 载体短暂忙，classify 原地立即重试同样失败 → 落到启发式；而「…结论如何？一句话概括」问号在句中，`endswith` 漏判 → 追问被错判 analyze（前端会错建重复任务）。
- **修复**：① `_dsh_turn`/`_stream_turn` 重试前退避 1.5s；② 启发式问句特征放宽到句中问号 + 疑问词（如何/怎么/什么/为什么/哪些/多少/吗/呢），与分类 prompt「拿不准倾向 qa」对齐；③ intent-classifier prompt 消歧规则：「问结论=qa（引用历史作答），要求继续/重新分析或出报告才 analyze/full」。

### 五、验证

- 冒烟 **155 PASS / 0 FAIL**（[19] 附件合并 7 条 + [20] digest 保真 7 条 + [21] 结论回写 4 条 + [10] 启发式 3 条 + prompt 消歧 1 条）。
- live 端到端闭环（新脚本 `scripts/live-task-loop.py` + `scripts/live-followup.py`）：chat/stream 意图 → 建任务（挂会话）→ 8-Agent 跑完（analyze 模式实测 ~16 分钟，code-locator/call-chain/impl-reviewer 真实检索源码）→ 结论回写会话 ✓ → 同会话追问「刚才结论如何」→ **意图 qa、回答准确引用「3 条需求 / 0 处代码证据」** ✓。
- 测试会话与任务已清理；8090 后台跑新代码（btj5q1b49）。

### 已知取舍（记录在案，非遗漏）

- requirement-analyst 输入 `source_text[:6000]`（超长文档截断，token 防护）。
- digest 12/15 条上限本身保留（token 控制），但现在超限显式告知模型。
- 图片 OCR 不做（M6+ 路线）：图片只传文件名/大小/类型注名。
- analyze 模式实测 16 分钟——真实工具检索耗时，非 bug；后续可考虑 Agent 并行化（M5+ 方向）。

## 2026-08-26 — Agent 能力优化 + 多轮会话（M3.2a）

状态：代码完成（⚠️ Bash 分类器持续故障，冒烟 [3][4][12][13][14] 新增断言待补跑
`python scripts/smoke-agents.py`；esbuild 构建待补跑）

本轮两条主线：**Agent 逐个优化**（10 个角色 prompt 契约收紧 + 补齐 3 个空 Skill）
与**会话连续性**（多轮对话不再一问就散）。

### 一、Agent 逐个优化（skills/rules 路线深化）

- **修复 call-chain steps 校验 bug**（`agent_validation.py` `_norm_steps`）：
  旧 `_str_list` 把模型输出的 steps 对象转成 `"{'project': ...}"` 字符串，
  入库时 `s.get()` 直接 AttributeError。现在对象/字符串双兼容统一规范化为
  `{project,component,call}` 三字段对象——这是 M2.3 上线后真实会炸的入库路径。
- **10 个 Agent 的 system_prompt 逐个收紧**（`agents.py`）：每个角色补判定标准
  与契约示例——requirement-analyst（一条规则一条需求、优先级标准、可验证断言）、
  code-locator（只报实查证据、requirement_id 标注归属、confidence 分档）、
  impl-reviewer（四档 status 判定线、fail 必须有证据）、quality-judge（risk 标准
  + recommendation 是动作）、report-writer（三视角各写什么、禁编数字）等。
  智能仍长在 Agent 角色里，代码零关键词。
- **补齐 3 个空 Skill**：`skills/test-design`（五类覆盖策略 + P0-P3 覆盖矩阵）、
  `skills/java-code-review`（分层核对 + status 判定 + 常见缺口模式）、
  `skills/vue-code-review`（前端核对链路 + 契约不匹配高危）。目录此前是空的，
  DSH 注入了也没内容。test-designer 挂 test-design、impl-reviewer 挂
  java-code-review。
- **code-locator 证据关联需求**：契约新增 `requirement_id`，校验层归并 REQ 引用
  （同 _remap_refs 三级归并），`code_evidence` 表加 `req_ref` 列（轻量迁移）。
  证据从「这任务的一堆文件」变成「REQ-001 的证据是这几个文件」。

### 二、多轮会话（会话连续性）

- **新表**：`conversations` + `chat_messages`（13 表），user/assistant 消息含
  intent 与 task_id 关联；DDL 双方言 + repository。
- **router.py 多轮化**：`classify`/`qa_answer` 带 conversation_id——每个会话一条
  常驻 DSH 路由会话（`conv-xxx--router`，模型自带跨回合记忆），另注入最近 12 条
  历史摘要兜底（DSH 会话被清理后仍能接上话）。追问「那帮我分析下它」由模型在
  会话语境里消解，intent-classifier prompt 补追问规则。
- **`/api/chat` 升级为对话回合端点**：classify + qa 回答 + 消息落库一体；
  新增 `GET /api/conversations`、`GET /api/conversations/{id}/messages`；
  `/requirements/tasks` 接 conversation_id（任务块写进会话流）。
- **前端线程化**（`requirements.tsx`）：左侧栏会话列表（+ 任务列表），主区完整
  消息流——问答气泡（user/assistant）+ 任务块（📦 点击展开活动流与结果面板），
  任务完成后 composer 不锁死，继续追问/提交新需求。新会话按钮清空重开。

### 三、requirement-analyst 校验失败重问（Agent 自纠错第一例）

- `_validation_is_poor`（全修/全丢/空输出判定）→ `_reask_agent`：校验质量差时
  **同会话**带上一次输出与校验反馈重问一次（validate_retry 进活动流可见），
  重问更差则保留第一次。空输出也重问确认——两次一致才采信「真没需求」，
  拿不准时多问一句不猜。

### 冒烟扩展（[3][4][12][13][14]）

steps 对象回归 + 入库拼接、code-locator req_ref 归并/无基准规范化、
多轮会话打桩（conv 会话复用/无会话回退 router-global/prompt 含历史规则）、
skill 挂载与文件非空断言、`_validation_is_poor` 阈值五断言。

## 2026-08-26 — Agent 子代理赋能：每个 Agent 成为该阶段主理，能力不足由子代理弥补（M3.2b）

状态：代码完成 + 冒烟 **108 PASS / 0 FAIL**（`python scripts/smoke-agents.py` 全绿通过）

用户原话：「我们不是还有子代理吗 agent 能力如果不足可以子代理去弥补 我需要一个强大的产品功能 每个agent都要各司其职 最强才行」

### 一、主理 Agent 模式（每个流水线 Agent 升级）

`agents.py` 8 个流水线 Agent 的 system_prompt 逐个改写为「**该阶段主理 Agent，对契约输出全权负责**」：
- **主理身份**：requirement-analyst 对 `items[]` 负责、code-locator 对 `evidence[]` 负责、
  call-chain 对 `chains[]` 负责、impl-reviewer 对 `assessments[]` 负责、test-designer 对
  `cases[]` 负责、quality-judge 对 `verdicts[]` 负责、report-writer 对 `views{}` 负责。
- **委派触发点**（能力补偿，非必经）：每个 Agent prompt 写明**何时该委派**——
  code-locator「3+ 项目或跨 Java+Vue+SQL」→ fork 各攻一个栈；call-chain「跨 3+ 服务」→
  spawn 各追一条链；impl-reviewer「需求>8 条或多分层」→ fork 按需求分组；test-designer
  「P0 五类齐全」→ fork 专攻一类；report-writer「多视角长报告」→ fork 分视角各写。
- **路由层 2 Agent**（intent-classifier / qa-assistant）显式声明「轻量、单回合直出、不委派子代理」
  ——路由层追求低延迟，不该为一句话意图判断起子代理。

### 二、agent-collaboration 共享 Skill

新建 `skills/agent-collaboration/SKILL.md`（流水线主理 Agent 共享）：两条子代理通道的
选择判据——**fork（同质并行/交叉验证，子代理继承上下文）**打同一个靶多视角覆盖盲区；
**spawn（异质分治，子代理无上下文）**拆不重叠的块。spawn 必须在 prompt 给足背景
（需求摘要+项目+证据），fork 只需给清晰靶子。合成纪律四条：去重保序、REQ 编号统一、
冲突仲裁、缺角补全；**最终契约 JSON 由主理输出**，子代理只递材料，合成权不下放。
另立「不该做」红线：不跨阶段、不把合成权下放、不委派逃避（简单任务直出）、不静默丢失、
不编造子代理没查到的路径。证据传递：子代理查到的 path/line/symbol 原样保留进主理输出。

### 三、冒烟 [15] 子代理赋能断言（108/0 全绿）

- `agent-collaboration/SKILL.md` 存在且 >500 字节
- 8 个流水线 Agent 全部含「主理」身份 + 委派触发点（fork/spawn/子代理）+ 引用
  agent-collaboration skill + 声明「合成/输出全权负责」
- 路由层 2 Agent 含「轻量」+「不委派子代理」
- `_activity_handler` 能把 `subagent_fork` / `subagent` 工具调用捕获进活动流
  （detail 含委派 prompt）——子代理委派在前端时间线可见

### 四、顺带修复冒烟漂移（上一轮遗留）

- report-writer 裸格式 `{"dev":..,"qa":..}` 在 `validate_stage` 里 `data.get("views")`
  返回 None 崩 `AttributeError`：改为先判 `data` 是不是 dict、`views` 是不是 dict，
  否则 `data` 本身当 views。修复了 [8] 的崩点。
- quality-judge「严重」缺中文别名 → `_RISK_ALIASES` 补 `严重→high`（与『高』一致）。
- requirement-analyst `critical` 别名 → P0（高严重度，原来误判为 P1）。
- 路由 [12] 会话 ID 用 `conv-abc` 会被拼成 `conv-conv-abc--router` 双前缀：改用裸 ID `abc`。

### cordis.yml 满血组合确认

`config/cordis.yml` 已含子代理双通道（`tool-subagent` spawn + `tool-subagent-fork` fork +
`tool-subagent-claude-code`）+ 工作流引擎 + skills 注入——本轮 prompt 升级后，Agent 委派
子代理的工程底座早已就位，不需要改 cordis。本轮是「把已就位的能力赋能给 Agent 角色」。

### 待补验收

- DSH 真实委派浏览器验收：提交一个跨 3+ 项目的需求，观察 code-locator 活动流出现
  `subagent_fork` 工具调用 + 主理合成后的 evidence（活动流 detail 含委派 prompt）。
- esbuild 构建（M3.2a 会话流 + 本轮无前端改动，但仍待补跑一次确认）。

## 2026-08-25 — M2.3 Agent 输出强校验层（流水线可信度升级）

状态：代码完成，冒烟脚本已落盘（`scripts/smoke-agents.py`；本轮分类器故障 Bash 暂不可用，待环境恢复后执行，预期全 PASS）

背景：此前 8-Agent 各阶段仅做 JSON 容错提取（raw_decode）+ 字段映射入库——
"模型输出有 JSON 就收"。这是 P1 技术债（PLAN.md「Agent 输出 Pydantic 强校验」），
也是 GPT 外部评审指出的「不能把有 Pydantic 模型等同于输出经过 schema 验证」问题。

新增 `backend/app/services/agent_validation.py`（纯函数校验层，~370 行）：

- **REQ-xxx 强制**：`REQ-1` / `2` / `req3` → `REQ-001` 顺序重排；下游阶段
  requirement_id 引用未知名时按位置/文本就近归并（含"标题当 ID"漂移），仍无法归并丢弃并计数。
- **枚举收敛 + 中文别名映射**：priority/kind/verdict/risk/status 非法值 → 规范默认值；
  实测 deepseek-v4-flash 会输出中文枚举（『边界』『高』『待复核』），先别名映射（五类用例/
  三档风险/四态结论/四态实现状态 全表）再兜底，保语义不丢。
- **数值钳制**：confidence ∈ [0,1]；line 正整数；confidence 字符串 → float。
- **fail 必须有证据**（核心原则落地）：impl-reviewer 输出 fail 但 evidence_refs 空
  → 自动降级 needs_review，杜绝"无证据 fail 结论"入库。
- **ValidationReport**：每阶段 valid/repaired/dropped + 明细，编排层带进 Agent 卡片结论
  （"输出 6 条需求（校验：6 条通过，2 条修复。需求 ID 规范化为 REQ-001…）"），人工可见修了什么丢了什么。

编排层接入（`orchestrator.py`）：

- `_run_agent` 返回三元组（校验后结果 / 会话信息 / ValidationReport）；8 阶段全量走
  `validate_stage()`，需求条目（阶段 1 产出）作为后续阶段引用归并基准传入。
- Agent 执行失败也写 `agent_sessions`（status=failed）——此前只有成功记录，失败阶段在
  会话表里消失。
- report-writer 的 `{"views":{...}}` 解包逻辑下沉进校验层。

router.py 与注册表统一：intent-classifier / qa-assistant 的 prompt 不再双份维护，
统一从 `dsh/agents.py` 注册表读取（改注册表即改路由）。

设计取舍：不用 Pydantic fail-fast 强校验——硬失败会把「可修复的格式漂移」变成
「整阶段降级」，与单阶段降级策略冲突；先修复、修不动才丢，是更稳的中间态。
评测基线（golden case）复用本校验层做输出对齐。

验证：`python scripts/smoke-agents.py`（离线，不依赖 DSH/DB）——脏数据 24 断言：
REQ 规范化/别名映射/fail 无证据降级/幽灵引用丢弃/双格式 views/None 边界。
（本轮 Bash 分类器故障未能执行，恢复后须补跑并在下条 CHANGELOG 记录结果。）

遗留：执行失败的 Agent 是否要带 prompt 摘要入 agent_sessions.payload（M3.2 一起做）。

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

