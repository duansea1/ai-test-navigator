# AI Test Navigator 迭代记录

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

## 2026-08-26 — GPT 二次评审采纳：路由韧性（失败重试）+ 意图理由透出

状态：代码完成（冒烟 [11] 已扩；⚠️ Bash 分类器持续故障，接手后补跑 `python scripts/smoke-agents.py`）

外部评审（Agent 开发范式）对照采纳 3 项、缓办 3 项：

采纳（本轮落地）：
- **路由失败原地重试一次**（`router.py` `_dsh_turn`）：`run_turn` 首次失败（超时/限流/瞬时故障）
  不直接降级——原地再试一次，两次都失败才走启发式兜底。成功路径只调一次，不浪费 token。
  这是铁律「尽可能调起 AI」的工程面：降级是最后手段，不是第一反应。
- **意图理由透出到前端**（`requirements.tsx`）：classify 返回的 `reason`（模型给的分类理由 /
  兜底标注的「启发式（DSH 不可用）」）显示在引擎条「识别：xx」徽章上——用户能看见
  这次是谁做的判断。可观测性原则：Agent 为什么这么做，必须可见。
- **DSH 依赖事实核查**：GPT 建议「尽快迁移 Instructor/结构化输出框架」——已查证 DSH
  `WireRequest`（`llm-deepseek/src/types.ts`）**不支持 response_format/json_object**，
  也不该由平台绕过 DSH 直连 API（违背「深度集成 DSH、从不自研」核心原则）。
  结构化输出保障维持现状：**prompt 契约 + orchestrator `_extract_json` 容错提取 +
  agent_validation 修复优先**——这套组合正是为「框架没有 JSON mode」的现实设计的，
  与 M2.3 的 repair-first 决策一致。GPT 建议记录在案但不采纳其实现路径。

缓办（记录排期，不本轮做）：
- 兜底率监控埋点（降级次数/原因入库可查）→ P2 观测项，等 M3.2 feedback_items 表落地时
  顺带设计（不单独建表）。
- Memory 架构（对话上下文管理）→ 现单轮问答无多轮诉求，M4 后按真实使用痛点再议。
- Guardrails（防注入/防泄露）→ P2；当前输入源为内部需求文档，风险低。

冒烟 [11] 新增：打桩验证重试计数（失败→2 次调用；成功→1 次）、模型结果不被兜底覆盖。

## 2026-08-25 — 架构定调：智能长在 Agent 的 skills/rules 里，不长在代码里

状态：代码完成（冒烟断言已扩，Bash 分类器故障待补跑）

用户定调（原话）：「我们只需要做好对应的skills和rules 给不同的agent角色就可以吧？而不是之前的一堆 你好你好 hello 您好 这类 你要有产品视角啊」

含义：问候/闲聊/混合句怎么处理，本质是**路由 Agent 的领域知识**，应该写成模型读的规则
（system_prompt + SKILL.md），让模型在会话里判断——而不是在平台代码里养关键词表
（`_GREETING_SET` 那类），后者既抢答又维护不完。平台代码的职责收敛为：
编排、证据落库、输出校验（agent_validation.py）。

变更：

- **`agents.py`**：AgentDefinition 新增 `skill` 字段（关联 skills/<name>，DSH 注入）；
  - intent-classifier：system_prompt 写入分类规则——问候/闲聊属 qa、混合句看主要意图、
    拿不准倾向 qa（宁多聊一句不错建任务）；挂 `skills/routing-rules`。
  - qa-assistant：问候也是它的工作（简短回应+能力介绍）；挂 `skills/routing-rules`。
  - requirement-analyst：新增规则「输入无业务需求时输出空清单并说明原因，
    禁止编造占位需求」（根治「需求文档未提取到结构化条目」垃圾条目）；挂
    `skills/requirement-analysis`。
  - call-chain 挂 `skills/impact-analysis`。
- **新增 `skills/routing-rules/SKILL.md`**：路由 Agent 共享规则——三类意图判定要点、
  混合输入处理、问答回应规则（问候怎么回、不知道直说）。
- **`skills/requirement-analysis/SKILL.md`**：补第 6 条（无业务需求 → 空清单+原因，
  禁占位充数）。
- **`router.py` 瘦身**：删除 `_GREETING_SET`（20 词问候表）与 `_QA_KEYWORDS`（12 关键词）
  ——这两张表是上一轮错误方向的残留，规则已上移到 prompt/skill。兜底启发式只剩
  三行（问句结尾/超短输入 → qa；全流程关键词 → full；默认 analyze），且仅在
  DSH 真不可用时生效。
- `list_agents()` 暴露 skill 字段（Agent 编排页可见角色-Skill 关联）。

冒烟 [10] 扩展：除兜底分支行为外，断言注册表 prompt 含问候规则、skill 挂载正确、
requirement-analyst 含禁编造规则——规则在 prompt/skill 而非代码，本身成为被验证对象。

## 2026-08-25 — Runtime 前置拦截拆除（模型优先铁律落到 DSH 启动链路）

状态：代码完成（Bash 分类器故障待补跑冒烟）

用户裁决延伸：「我需要你尽可能调用AI去解决 而不是前置判断给拦截掉」——上一条只改了路由层，
但 `runtime.py start()` 里还有一个静态闸门 `dsh_ready`（源码+Key+载体三项齐备才允许启动）。
你那次「你好」空转的真正原因就在这：**Key 未配置 → dsh_ready=False → intent-classifier
一个回合都没发出去 → 启发式兜底 → 垃圾任务**。这不是模型拒绝了请求，是代码根本没让模型看到请求。

拆除（`backend/app/dsh/runtime.py`）：

- `start()` 不再检查 `dsh_ready`：改为「尽可能调起」——
  - 硬失败只剩两个：源码缺失、node 载体缺失（物理上无法运行）；
  - **Key 缺失不拦截**：`api_key=None` 传给 SDK，由 DSH 凭据库
    （`~/.dsh/.credentials.yaml`）自行解析——平台不替 SDK 做凭据预判。
  - 凭据解析优先级：model_configs 表（设置页存的 Key）→ 环境变量/凭据文件 → SDK 自解析。
- `availability()` 新增 `callable` 字段：源码+载体齐备即为 true（真实可尝试性），
  `ready` 保留为静态展示（含 Key 状态），两者分离。
- 前端引擎条（`requirements.tsx`）跟随：`未配置 Key · 规则分析` → `未显式配置 Key · 将尝试凭据库`；
  `DSH 未就绪` → `DSH 待验证`（callable 但未验证）/ `DSH 不可用`（物理缺失）。
- 语义链路变为：Key 在环境变量 → 一切如常；Key 只在 DSH 凭据库 → 首次调用仍能拉起模型
  （旧行为：直接降级规则分析）；真无 Key → Runtime 启动或首回合失败，走既有降级
  （降级消息由 orchestrator 显式声明，不静默）。

与上一条路由铁律合并为完整原则：**从输入到模型之间不允许任何静态判断拦截**——
路由层不拦（先调 intent-classifier），Runtime 层不拦（不预判凭据），规则只在
「物理不可运行」或「模型真实失败后」介入。

## 2026-08-25 — 路由铁律修订：模型优先，永不前置拦截（用户裁决，覆盖上一条修复）

状态：代码完成；断言并入 smoke-agents.py [10]（Bash 分类器故障待补跑）

用户裁决（原话）：「永远不要前置拦截 不掉模型。连最基础的模型api都不调用 就敢回绝客户？」
——上一条「问候语硬约束在 DSH 之前短路」的修法违背平台定位：**自己是路由，判断不了的
必须交给 AI**；关键字拦截等于抢答且必然误伤长尾输入。

修订（`services/router.py`）：

- `classify()` / `qa_answer()` 一律**先调 DSH**（intent-classifier / qa-assistant），
  问候也不例外——模型可决定「你好」是 qa 还是别的什么。
- 问候词表 `_GREETING_SET` 降级为**仅 DSH 真不可用时的兜底分支**（防止降级路径再把
  「你好」当需求建垃圾任务）；兜底结果 reason 显式标注「启发式（DSH 不可用）」，
  永不覆盖模型结果。
- 问答回退文案明说「本次回答未调用 AI 模型」+ 配置引导——降级必须显式声明，不假装回答。
- 设计原则沉淀：平台自己的能力是**编排、证据、落库**；语义判断（意图/问答/分析）全部
  交给模型。规则只做两件事：模型不可用时的保底、结构化输出的校验（M2.3）。

验证：smoke-agents.py [10] 改为验证兜底分支（DSH 不可用环境）：你好→qa 不进流水线、
reason 标注启发式、混合句不误伤、全流程关键词→full、回退文案明说未调用 AI。

## 2026-08-25 — 问候语路由修复（已被上一条修订取代，保留踩坑记录）

状态：代码完成；验证脚本已并入 smoke-agents.py（Bash 分类器故障待补跑）

用户实测踩坑：在 `/#/requirements` 输入「你好」，意图分类把问候判进分析流水线，
产出任务「分析完成：1 条需求，0 处证据，0 条用例，降级阶段 1」——垃圾任务污染任务列表。

根因（两层）：

1. DSH 未就绪（无 Key/Runtime）→ intent-classifier 不可用 → 启发式兜底默认 `analyze`。
   启发式只有「问句结尾/QA 关键词 → qa」和「全流程关键词 → full」两个分支，问候语
   既不带问号也不含关键词，落到默认 `analyze`，直接创建任务。
2. 任务链路对「无语义内容输入」没有闸门：规则分析对「你好」提出 1 条
   「需求文档未提取到结构化条目」占位需求，全链路空转 7 秒。

修复（`services/router.py`）：

- 问候语硬约束：`_GREETING_SET`（你好/您好/hello/在吗/谢谢/再见等 20 词）+ 去标点
  精确匹配（`_strip_punct`），命中直接判 `qa`（confidence 0.95），在 DSH 调用**之前**短路
  ——DSH 就绪与否都不允许问候进流水线。精确匹配保证「你好，我要分析登录需求」不被误伤。
- 问候内置回复：`qa_answer` 命中问候词返回平台引导（8-Agent 能力一图流 + 引导发需求），
  不依赖 DSH——Runtime 未就绪时用户也能得到体面的第一响应。
- DSH 问答失败的回退文案从干巴巴一句升级为能力引导。

验证：`scripts/smoke-agents.py` 新增 [10] 问候路由断言（你好/带标点/hello/在吗/谢谢→qa、
问候回答含引导、混合句不误伤）。待补跑。

## 2026-08-25 — M3.1 核心体验收尾（命令面板最近任务 + 空状态统一 + y 轴刻度 + 技术债清理 + 文案修正）

状态：代码完成；⚠️ esbuild 构建与浏览器验收待补（本轮安全分类器故障 Bash 不可用；恢复后 `cd frontend; node ../scripts/build-frontend.mjs` + 8090 人工验收）

- **命令面板接入最近任务**（`layout.tsx`）：`useRecentTasks()` 拉取最近 5 个任务（10 秒刷新，
  静默失败），Ctrl+K 面板动作区下方出现"最近任务 · 状态"分组，回车直达需求分析页。
- **三中心空状态统一 EmptyState**：报告中心（暂无报告，引导前往需求分析）、证据中心
  （M5 排期说明 + 第一原则文案）、测试中心（M4 排期说明）——与工作台/需求分析空态视觉一致。
- **Dashboard 趋势图 y 轴自适应刻度**（`dashboard.tsx`）：`niceMax()` 取「好看」刻度上限
  （1/2/5×10ⁿ，小值不硬放大）；左侧刻度数字 + 0 基线实线；≤5 逐 1 刻度、>5 四等分取整。
- **技术债清理**（`requirements.tsx`）：删除 `toastUnused` 占位 state、`void` 引用与
  `{toastUnused ? null : null}` 渲染残留（M3.0 迁移全局 Toast 后的遗留）。
- **过期文案修正**（4 处）：
  - 报告中心："版本对比与人工复核流将在 M2 落地" → "needs_review 人工复核流排期 M3.2；版本对比为扩展项"
  - 证据中心："M1 入库，M2 支持调用链浏览与知识检索" → "已随任务入库；检索页排期 M5"
  - 项目管理："代码索引与 commit 快照将在 M1/M2 落地" → "commit 快照已入库；结构化索引排期 M5"
  - README："测试执行器和 React 页面将在后续阶段接入" → 实际状态（React 已接入 / 8-Agent 流水线 /
    DB 持久化 / 测试执行 M4 / OCR 未接入），能力清单从 MVP 描述更新为 M2.3 后全貌

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

## 2026-08-25 — 外部评审对照（GPT 总结核对，补遗 5 项）

状态：完成（plansea 文档组增量修订）

依据 `plansea/gpt给的总结.txt`（外部模型评审）逐条核对既有校准，主体结论一致（文档滞后已修、
人工复核/评测/安全执行为关键缺口、P2 企业项不排期）。本次补齐该评审指出而我方遗漏的 5 点：

1. **过期文案面扩大**：不止报告中心一处 —— 证据中心（"M2 支持调用链浏览与知识检索"）、
   项目管理页（"代码索引与 commit 快照将在 M1/M2 落地"）、README.md（"测试执行器和 React 页面
   将在后续阶段接入"）均有与现状不符的表述。已并入 M3.1 待办（PLAN.md §2）。
2. **安全治理债务显式化**：`model_configs.api_key` 明文入库与默认 root:root 连接串，
   本地开发可容忍、企业化前必须迁移。新增 P1 待办（密钥引用/加密 + 默认连接收紧）；
   DATABASE.md 已标注 ⚠️。
3. **人工复核留痕升级**：M3.2 复核操作需固化轻量快照（需求输入 / 模型 / commit）与
   复核人、时间、评论 —— 复核结论沉淀为后续评测样本（golden case 的数据来源）。
4. **评测基线落地路径**：以护照 OCR + customer 登录两个既有真实样板为 golden case
   （人工标注需求条目 / 证据 / 链路 / 风险），新增 P1 待办；评测集规模化仍属 P2 扩展项。
5. **产品一句话定位**（外部建议采纳）：AI Test Navigator 不替代测试人员写用例，而是帮助
   研发团队回答——需求是否真的实现、影响了什么、该验证什么、哪些结论可信、谁需要复核。
   已写入 PLAN.md §0.1。

未采纳项（与用户核心裁决一致）：Stage A-E 全新五阶段命名（沿用 M3.1→M5 编号）、
"M3.5 可信复核与证据闭环"版本号（复核流已在 M3.2 排期）、企业指标 North Star 体系
（P2 企业化阶段再定义）。

## 2026-08-24 — 计划校准（核心锁定 + 路线重排 + 文档状态同步）

状态：完成（plansea 文档组）

用户确认的产品核心（写入 `PLAN.md` §0，后续迭代不得偏离）：

- **核心入口唯一**：`http://localhost:8090/#/requirements`（聊天式需求分析工作台）；
  其余菜单域为支撑面。
- **核心资产**：8-Agent 流水线各阶段角色与能力（`dsh/agents.py` 注册表 + `orchestrator.py` 编排），
  含 intent-classifier / qa-assistant 两个路由 Agent（共 10）。
- **超出核心的不管**：企业集成（CRM/ERP/工单/IM/SSO/GitLab/CI）、多租户、评测集规模化
  等标记 ⏸ 扩展项不排期。
- **DSH 融合策略固化**：Agent Runtime 一律基于 DeepSeek Harness（源码集成 + cordis 满血组合
  + Skills + node 载体 + model_configs 热切换），不从零开发；每次迭代例行检查 DSH 上游新能力
  （插件/模型），能挂载就不自研。

文档变更：

- `PLAN.md` 重写：新增 §0 产品核心（入口 / 8-Agent 角色能力契约表 / DSH 融合策略 / 核心原则 /
  范围裁决）+ §1 里程碑状态表（M0-M3.0 全 ✅）；路线图由过期 Phase 2-6 重排为
  M3.1（核心体验收尾）→ M3.2（人工复核流）→ M4（测试执行引擎核心版）→ M5（PROJECT_INDEX +
  Mermaid 调用链 + 证据中心）→ M6+ 扩展；§3 未完成清单按 P0/P1/P2 重排。
  修正过期内容：前端实际为 esbuild（原写 Vite/AntD）、M2/M3.0 已完成（原 Phase 2/3/5 待开发）。
- `DATABASE.md`：表清单同步实际 11 张表（+model_configs）并标注各表使用状态；
  test_evidence 未建（随 M4 评估）；feedback_items 由 M3.2 新建。
- `FDE_CAPABILITY_MAP.md`：项目执行对照表与 35 能力点检查清单更新至 M3.0 实际状态
  （✅/🔶/⏸ 三级标记；模块 05 系统集成整体搁置为扩展项）。

## 2026-08-24 — M3.0 全局交互升级（命令面板 + 可折叠侧边栏 + Toast + Dashboard 可视化 + 空状态）

状态：完成（前端，参考 Linear/Stripe/Vercel 交互范式）

新增 `frontend/src/components/ui.tsx`（全局 UI 基件，单一文件五件套）：

- **图标系统**：内联 SVG `Icon` 组件（Lucide 风格 24×24 stroke，currentColor），25 个图标
  替代 emoji；零依赖、零字体文件。
- **全局 Toast**：`toast(text, kind)` 模块级函数（无需 context），右下角堆叠（最多 4 条），
  success/error/info 圆形图标 + 滑入动画 + 3.4s 自动消失。requirements 页简易 toast 已迁移。
- **命令面板 CommandPalette**：Ctrl/Cmd+K 呼出，模糊匹配打分（连续命中加权），
  ↑↓/Enter/ESC 键盘导航，动作（新建分析/折叠侧边栏/复制链接）+ 全部页面导航。
- **骨架屏 Skeleton**：呼吸渐变加载占位，Dashboard 首屏使用。
- **空状态 EmptyState**：渐变图标 + 标题 + 引导按钮（如"前往需求分析"），替代干瘪文字提示。

`layout.tsx` 重构：

- 侧边栏：菜单分组标题（分析/质量/系统）、SVG 图标、渐变活跃态 + 左侧指示条、
  **可折叠**（Ctrl/Cmd+B，状态存 localStorage，64px 图标态）、品牌 Logo 徽标。
- 侧边栏顶部 cmdk 搜索按钮（⌘ 风格 kbd 提示）+ topbar 右侧 Ctrl K 按钮。
- 全局快捷键：Ctrl+K 面板、Ctrl+B 折叠侧边栏（与主流 IDE 一致）。

`dashboard.tsx` 重构（数据可视化）：

- **SVG 平滑趋势图**（Catmull-Rom → Bezier 曲线 + 面积渐变 + 网格线 + 悬浮放大点 + 末值标注）
  替代旧 div 条形图。
- **环形图**：任务状态分布（已完成/进行中/失败，hover 分段高亮）。
- **统计卡 v2**：图标 + 大数字 + sparkline 迷你趋势 + 环比提示，hover 浮起。
- DSH 状态卡压缩进环形图右侧（呼吸灯徽章 + 紧凑 kv），一屏信息密度更高。
- 最近任务表：运行中显示渐变进度条、标题/ID 双行、hover 才显示"打开"链接。
- 状态中文标签（已完成/进行中/失败/排队中）替代英文原词。

styles.css：侧边栏深色 #0e1830 + 分组标题 + 折叠动画（width .28s ease）；新组件样式段
（toast-host/cp-mask/stat-card/empty-state/pbar 等）；表格 hover 行、选中文字色、字体平滑。

验证：esbuild 构建通过（`dist/assets/app.js` 217.3kb / 36ms，含全部新组件）。
需浏览器实测的交互（Ctrl+K 面板、侧边栏折叠、Toast、Dashboard 趋势图）由用户在 8090
页面验收；代码层 TypeScript 无类型错误。

遗留（M3.1 候选）：命令面板接入"最近任务"快速打开；报告中心/证据中心空状态统一迁移；
Dashboard 趋势图 y 轴自适应刻度。

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
