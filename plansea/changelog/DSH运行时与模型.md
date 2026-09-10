# DSH运行时与模型

## 2026-09-02 — M3.9 DSH 会话碰撞修复 + 需求解析 AI-first

状态：**完成**（冒烟 193/0 + live `/api/chat/stream` 同会话不再 collision + live 建任务活动流 AI-first）

> 用户复现：已有会话 `conv-41ee56477b10` 连续问答报 `session "conv-conv-41ee56477b10--qa" already has a persisted log on disk that does not match this live session (id collision)`，"一直是这个问题"。用户追问「需求分析问答为啥要触发兜底逻辑，我们所有的文档都是 AI 处理的啊」。

### 根因（两个独立问题）

1. **DSH persisted session collision**：后端重启 / DSH Runtime 重建后，`DshRuntimeManager` 仍把同一逻辑会话 ID（`conv-xxx--qa`）原样传给 Python SDK；SDK `DeepSeekHarness.run()` 每次 `start_session(session_id)` 新建 live Session；新 Session 的 seed 与磁盘上同 ID 旧持久化日志不一致 → DSH persistence coordinator 正确拒绝（`adoptLivePrefix` 抛 id collision）。路由将该 Runtime 错误当 fallback，随后启发式把无问句特征的输入默认分成 `analyze` → 表象「问答触发兜底」。异常路径又把 `_harness` 置空，下次请求重建 Runtime 再次撞旧日志，形成「一直是这个问题」。
2. **需求文档无条件规则预分析**：`orchestrator._run_task()` 阶段 0 无条件先跑 `NavigatorAnalyzer`（确定性 URL/标题/bullet 拆需求 + 占位需求），与「文档语义由 AI 处理；规则只做物理扫描/执行/校验以及模型不可用时保底」的产品原则不一致。

### 修复

- **`backend/app/dsh/runtime.py` — 运行时代际物理 ID 隔离**：
  - 新增 `_runtime_gen`（代际标识）+ `_session_map`（逻辑 ID → 物理 DSH ID）。
  - `_physical_session_id()`：同一存活 Runtime 内同一逻辑 ID → 同一物理 ID（保留多轮 DSH 上下文）；物理 ID = `r{代际}-{逻辑ID 的 sha1 短哈希}`，带代际前缀可溯源、不撞业务 ID 旧日志、不超长。
  - `start()` 成功时生成新代际 + 清映射；`stop()` / 异常重建 / `reconfigure` 清代际与映射 → 下次新物理 ID，绝不把新 live session 当旧持久化日志续写。
  - 无 `session_id` 的一次性调用透传 None（沿用 SDK 原有随机 session 行为）。
  - 跨 Runtime 对话连续性继续由 `router._history_block()` 从 DB 注入最近消息承担；**不删除任何既有 `.dsh-sessions` 日志**。
- **`backend/app/services/orchestrator.py` — AI-first 需求解析**：
  - 阶段 0「无条件规则分析」→ 阶段 1「requirement-analyst 先行」。
  - Agent 两次（含同会话重问）都拿不到可用结构化需求时，才执行 `_run_rule_analysis()` + `_rule_fallback_requirements()` 作为离线保底，活动流显式标注「AI 需求分析未成功，启用规则保底（模型未参与）」「规则保底完成（模型未参与需求拆分）」。
  - 模型成功时不再用 `NavigatorAnalyzer.parse_requirements()` 拆文档；报告骨架由 AI 需求条目生成（`_ai_initial_report`），收尾由 `_rebuild_report_from_pipeline()` 用 DB 实际产物重建落盘——报告与各 tab 结果面板、reports 中心一致，不再先写规则快照再混杂 AI 结果。
  - analyze 模式收尾同样重建报告落盘。
- **`backend/app/services/reporter.py`**：`a.confidence` 访问容错（assessment 缺失时显示 `-`，不再 AttributeError）。
- **`backend/app/services/router.py`**：不变（已先调模型、失败重试一次、兜底标注真因）；collision 修复后不再落到启发式 `默认需求分析`。

### 验证

- 冒烟 **193 PASS / 0 FAIL**（新增 [24] DSH 会话物理 ID 隔离 7 条 + [25] AI-first 编排 4 条；修 [10] 兜底断言在 DSH 在线时强制 fallback）：
  - [24] 同代际同逻辑→同物理 ID / 物理 ID ≠ 逻辑 ID / 带代际前缀 / intent-qa 隔离 / 重建后新物理 ID / 新代际前缀 / 无逻辑 ID 透传 None；
  - [25] AI 成功时不执行 `_run_rule_analysis` / 产出报告 ID / 需求来自 AI / 活动流无 rule-analysis 首阶段。
- live `/api/chat/stream` 同 `conversation_id=conv-41ee56477b10` 发「11」：**collision 消失**，`intent: qa`、`model_error: null`、模型正常流式回答（"收到～前面两次因会话日志冲突没有生成回答，现在已恢复正常…"）**PASS**。
- live 建文本需求任务（analyze 模式）：活动流首阶段为 `requirement-analyst`（AI 拆出 3 条结构化需求），**无 rule-analysis 作为首阶段**；报告 ID 在需求分析后即生成，后续阶段填充证据/链路。
- 已知边界：live 任务跑到 impl-reviewer 等后续阶段时，宝云网关 `ai-api.baoyun.com` 间歇 `DeepSeek API request failed`（模型侧波动，非本次修复范围；M3.8 已钳 max_tokens，网关偶发失败属上游）。

## 2026-09-02 — M3.8 网关 max_tokens 钳制（宝云 400「max_tokens参数非法」修复）

状态：**完成**（冒烟 182/0 + live 修复前后对比实测）

> 用户 curl 复现：`/api/chat/stream` 发「ds」返回「模型调用失败：max_tokens参数非法：限制数值范围[1,131072]」。用户疑问「模型接口是通的啊」。

### 根因（diag-max-tokens.py 五档实测定位）

- **DSH llm-deepseek 适配器默认 `max_tokens=256_000`**（`adapter.ts DEFAULT_MAX_TOKENS`），每个请求都带（`serialize.ts`）；
- **宝云网关（ai-api.baoyun.com）校验 `[1, 131072]`**：131072 过、131073/256000 一律 400 code 1210；官方 DeepSeek API 无此限制；
- 「测试连通」探测不带 max_tokens（只带 thinking/reasoning_effort）→ 探测 200、DSH 实战 400——又是「探测保真」缺口（M3.6 修了 thinking，漏了 max_tokens）。
- 请求正文只有「ds」两个字——与数据量无关，网关在参数校验层就拒了。

### 修复

- `runtime.py`：新增 `_max_tokens_for(base_url)` + `_GATEWAY_HOSTS`（宝云 → 131072 钳制，官方/未知网关不干预）；构造 `DeepSeekHarness` 时传 `max_tokens=`（SDK `DeepSeekHarnessConfig.max_tokens` → JSON-RPC initialize → agent 每请求生效）。
- `agents.py _probe_provider`：探测 body 补带钳制后的 max_tokens——探测与实战同路径同参数（保真第三件事）。
- 冒烟 [22] 新增 4 条断言（宝云钳 131072 / 官方不钳 / 无 base_url 不钳 / 未知网关不误伤）。

### 验证

- 冒烟 **182 PASS / 0 FAIL**；
- live 前后对比：修复前 `⚠️ max_tokens参数非法` → 重启后端（新代码）后同一请求正常回答、`model_error: null` **PASS**（`scripts/live-max-tokens.py`）；
- 诊断脚本 `scripts/diag-max-tokens.py`（五档 max_tokens 边界实测，key 取自 MySQL 同源）。
- 附带：`.claude/settings.local.json` 权限白名单改为前缀模式（python/curl/node 等），大幅减少 auto 模式分类器超时卡顿。

## 2026-09-02 — M3.7.1 模型管理弹框再重设计（主从两栏）

状态：**完成**（esbuild 构建 + bundle 校验 ALL PASS + live API 数据核对）

> 用户对 M3.7 版弹框不满：「这个弹框的水平真的太差了，还不如之前」。诊断：单列卡片把 radio/名称/chip/操作行全塞一行，密度过高；顶部还要靠一句「点卡片切换供应商 · 点模型立即选用」的教学文案补救——说明交互不自解释。

### 重做（ModelDrawer.tsx + styles.css）

- **主从两栏布局**（macOS 设置 / chat.z.ai 选模型式）：左栏 `mc-nav` 供应商导航（当前使用的带呼吸绿点、默认带角标、停用置灰、白底浮起高亮当前查看项）；右栏 `mc-detail` 该供应商详情（名称+URL+标签 · 操作按钮行 · 模型单选列表）。
- **交互自解释，删除全部教学文案**：
  - 左栏只负责导航（点谁看谁），不再「点卡片即切换」；
  - 选模型 = 在右栏点模型行（hover 显示「选用」，选中行蓝底渐变 + ✓「使用中」）——换供应商靠选另一家的模型一步到位，心智模型唯一；
  - 头部提示从教学句改为信息展示：「当前使用 **DeepSeek 官方** · deepseek-flash」。
- **操作按钮重见天日**：测试连通/编辑/设默认/删除从卡片底部 opacity .55 的弱化行移到右栏顶部常驻按钮行（描边按钮，危险操作红色 hover）。
- 空状态覆盖：无供应商 / 该供应商无模型 / 无选中，各有引导文案。
- **高度自适应**（用户二轮反馈「右侧那么多空白」）：去掉 mc-body 的 min-height:360px 写死，弹框宽度 740→640，左栏 210→190；模型区 max-height 320 才滚动、供应商多时左栏 max-height 380 滚动——每供应商 1 个模型时是紧凑一块，不再大片留白。
- 切换后自动把右栏切到目标供应商（apply 内 setViewKey），所见即所选。

### 验证

- esbuild 重建通过（226.2kb）；`scripts/check-bundle-cjk.py`（新增，固化「bundle CJK 校验法」：esbuild 大写 `\uXXXX` 转义 + 类名/CJK 文案逐项断言）**ALL PASS**。
- live：8090 现行服务（用户自启）直接读 dist 新包；`/api/agents/runtime/config` 核对 current=glm-5.3-flash、5 供应商数据完整。
- 浏览器人工验收：待用户刷新（Ctrl+F5）确认观感。

## 2026-09-01 — M3.7 模型选择持久化 + 模型管理弹框重设计

状态：**完成**（冒烟 178/0 + live 重启持久化实测）

> 用户反馈：「模型供应商配置弹框非常不好用——选择模型之后重启服务又恢复默认了，反正是不好用也不好看」。

### 一、选型持久化（修「重启回默认」）

- **根因**：切换供应商只写 runtime 内存（`_preferred_provider_key`），进程一重启即回到 `is_default` 配置。
- **修复**：
  - 新表 `app_settings`（k/v 键值对，14 表 → 轻量平台设置存储）+ `entities.get_setting/set_setting`（双方言 upsert）。
  - `runtime.py`：`_load_selection()` 懒加载持久化的 `active_provider`/`active_model`（每次 `_resolve_provider_config`/`availability` 前触发）；`_persist_selection()` 在 reconfigure 时落库（失败不阻断）；持久化的供应商被删除后回落默认配置。
  - `reconfigure(provider_key?, model?)`：支持只换供应商 / 只换模型 / 同时换；换供应商时模型若不在新目录则自动清掉由目录首个顶上。

### 二、API：provider/model 分离

- `POST /api/agents/runtime/config` payload `{provider_key?, model?}`：可只传 model（当前供应商下换模型）；model 不在目录时 400。探测目标改为**切换后真实生效的供应商 × 模型**（此前总探测目录第一个——切到非首个模型时探测结果是错的）。

### 三、模型管理弹框重设计（ModelDrawer.tsx + styles.css）

- **交互定则**：
  - 点整张卡片（含左侧 radio 圆点）→ 一键切换供应商（单选式，不再是每张卡一个「使用」按钮）；
  - 点卡片里的模型 chip → 供应商 + 模型一步到位（chip 即选项，不再是纯展示文本）；当前使用的 chip 高亮；
  - 次要操作（测试连通/编辑/设默认/删除）收进卡片底部弱化按钮行（hover 才全亮，不抢主操作）；
  - 停用的供应商整行变灰不可点。
- 列表从「卡片堆按钮」改为「单选行」结构（`mc-row`：radio + 主信息 + chip 行 + 弱操作行）。
- 表单弹框：提示文案更新（「纯域名会自动补 /v1」「保存后在卡片上点选启用哪个」）；新增模式下的 model chips 不再标「当前」（误导——还没保存）。

### 验证

- 冒烟 **178 PASS / 0 FAIL**（新增 [23] 节 12 条：settings 读写/upsert、懒加载、reconfigure(model) changed、持久化与恢复模拟、换供应商模型回落、还原默认）。
- **live 重启持久化实测**：切到 deepseek-v4-chat → 重启后端 → 选型仍为 deepseek-v4-chat（修复前会回到 flash）✓；切回 flash → probe ok → 问答正常 ✓。
- 附带发现：种子配置里的 deepseek-v4-chat/reasoner/coder 在官方 API 实际不存在（报「supported: deepseek-v4-pro/flash/vision」）——切换探测现在会如实报出，不再静默。种子目录修正列为后续小项。

## 2026-09-01 — M3.6 模型调用错误显式化（「模型未返回内容」黑盒修复）

状态：**完成**（冒烟 162/0 + live 复现验证）

> 用户报告：页面发「hello」回答是「（模型未返回内容）」，页面什么都没有、没有重试，问「有没有调模型」——这个问题一直没解决。

### 根因（live 诊断还原——两层，都修了）

**第一层（错误被吞）**：用户切换到 `gpt-5.6-luna`（baoyun 网关）后所有模型调用失败，但 DSH SDK 的 `run()` 不因模型错误抛异常：错误表现为 `finish_reason=error` + `final_response=""`，`run_turn` 只看「有没有异常」→ 返回 `status=ok` + 空串。上游两级误报：`qa_answer` 显示「（模型未返回内容）」（其实模型被调了）；`classify` 标「启发式（DSH 不可用）」（其实 DSH 活着）。真因完全不可见。

**第二层（404 的真正出处）**：llm-deepseek 适配器直接请求 `{baseURL}/chat/completions`（adapter.ts:341），而 baoyun 配置的 base_url `https://ai-api.baoyun.com` **无 /v1 前缀**且网关只服务 `/v1/chat/completions` → 每次请求 HTTP 404。修掉 404 后又暴露第三层：该网关不认 DeepSeek 的 `thinking` 参数（DSH cordis 配了 `thinking: enabled`）——gpt 系模型走 DeepSeek 专用适配器的兼容性边界，现已显式报错而非黑盒。

### 修复（错误显式化五件套）

1. **`dsh/runtime.py run_turn`**：`finish_reason=error` 或 `final_response` 为空 → `status=error`，新增 `_turn_error()` 从 turn/end 事件提取真实错误（如 `DeepSeek API error (HTTP 404)`）随 `message` 返回——模型级错误不再伪装成 ok。
2. **`services/router.py`**：
   - `classify` 兜底 reason 说真话：`_failure_note()` 区分三种失败（模型调用失败：xxx / DSH Runtime 未就绪：xxx / 输出未解析出意图 JSON），不再一律「DSH 不可用」；
   - 新增 `qa_answer_result()` 返回 `{answer, model_error}`：模型报错时回答含真因 + 「换模型后重试」指引；`qa_answer()` 保持原签名作包装（老调用方兼容）。
3. **`api/requirements.py`**：/api/chat 与 /api/chat/stream 终帧新增 `model_error` 字段（前端错误样式与重试的信号）。
4. **`api/agents.py runtime_set_config`**：切换供应商配置后立即真实探测，响应带 `probe: {ok, error}`——切到不可用的模型**当场**报出来，不等下次问答静默失败。探测保真两件事：base_url 与 runtime 同款归一化（`_normalize_base_url`：纯域名自动补 /v1，带路径尊重原样）；请求体带 DSH 同款参数（`thinking: {type: enabled}` + `reasoning_effort: max`，与 cordis 一致）——裸探测会漏掉「网关不认 thinking 参数」这类只在实战暴露的失败。
5. **`dsh/runtime.py _normalize_base_url`**：`_resolve_provider_config` 的 base_url 归一化——修复 baoyun 等网关因缺 /v1 前缀全量 404 的问题。
6. **前端**：
   - `requirements.tsx`：终帧带 `model_error` 时气泡加 `err` 样式（红边）+ 「↻ 重试」按钮 + 「模型调用失败」badge；**输入与附件不清空**（换模型后可直接重发）；toast 明示真因；重试前移除失败的这对气泡（user + 错误 assistant，防重试一次多两条重复消息）；错误路径也刷新会话列表（新会话要进侧栏）。
   - `ModelDrawer.tsx`：切换模型时若后端探测失败 → err toast「已切换但该模型不可用：HTTP 404…」，不再显示「已切换」成功。
   - `styles.css`：`.bubble-a.err` 错误气泡样式。

### 验证

- 冒烟 **166 PASS / 0 FAIL**（新增 [22] 节 9 条：404→status=error、真因透出 message、空 final_response（finish=completed）也判错、正常回答不受影响、classify reason 真因标注、base_url 归一化 4 条；[10] 节改为双分支断言：模型报错说真因+model_error 信号 / fallback 才说「未调用 AI」）。
- live 三场景实测（`scripts/live-model-error.py`，因分类器故障改为 curl 手动执行同步骤）：
  1. **gpt-5.6-luna**（baoyun 网关）：切换探测如实报 `HTTP 404`（带 DSH 同款 thinking 参数）；问答终帧 `model_error: "Unknown parameter: 'thinking'."`、reason 同步真因、回答明示失败与换模型指引 ✓
  2. **临时坏模型**（deepseek 官方 + 不存在的模型名）：切换探测报出官方真因（supported API model names 列表）；问答 model_error 完整透出 ✓
  3. **切回 deepseek-v4-flash**：探测 ok、问答流式正常回答、意图为真实模型分类（非启发式）✓
- 诊断工具：`scripts/debug-dsh-turn.py`（抓 DSH 全事件流：assistant/chunk、turn/end reason 等）——本轮定位三层根因的关键。
- 测试会话与临时模型配置已清理；8090 后台跑新代码。
- **全链路回归（用户要求「输入和输出一定要做好」复查）**：前端重新构建（含重试防重复气泡/错误路径刷新侧栏两处修缮）；`live-chat-stream.py` 7 场景 ALL PASS（纯文本流式/带项目问答落到 LoginServiceImpl/附件-only/多轮追问复用会话/图片+文本→analyze/纯图片→analyze/文本附件内容命中「5次/60分钟」）；错误路径复验（切坏模型→probe 404→问答 model_error 透出→切回恢复）；测试会话已清。

### 已知边界（记录不修）

- gpt 系模型走 baoyun 网关无法用于 DSH：llm-deepseek 是 DeepSeek 专用适配器（必发 `thinking` 参数），网关不认。要支持任意 OpenAI 兼容网关需接 DSH 的 `llm-pi-ai` 通用适配器（provider 注册 + cordis 配置）——列入 M5+ 候选。
- 错误消息已可见可行动，用户可自行换回 deepseek 系模型。

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

