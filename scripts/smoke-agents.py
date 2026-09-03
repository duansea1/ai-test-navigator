"""M2.3 冒烟：Agent 输出强校验层（agent_validation.py）离线验证。

不依赖 DSH / DB / 网络——直接喂脏数据（模拟 deepseek-v4-flash 的真实漂移风格），
断言：规范化、修复计数、丢弃计数、fail 无证据降级、引用归并。

运行：python scripts/smoke-agents.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.agent_validation import ValidationReport, validate_stage  # noqa: E402
from app.services.router import classify, qa_answer  # noqa: E402
import app.dsh.agents as reg  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def main() -> int:
    print("== M2.3 Agent 输出强校验冒烟 ==")

    # ── 1. requirement-analyst：REQ-xxx 强制 + 优先级收敛 + 脏数据丢弃 ──
    print("[1] requirement-analyst")
    dirty_reqs = [
        {"id": "REQ-1", "title": "登录密码错误锁定", "priority": "P0", "acceptance_criteria": ["连续错误5次锁定"]},
        {"id": "2", "title": "五种登录方式", "priority": "critical"},           # 裸数字 ID + 非法优先级
        {"id": "req3", "title": "风险关注点输出"},                                # 非标准前缀
        {"title": "", "description": "无标题应丢弃"},                            # 无标题
        "not-a-dict",                                                            # 非对象
    ]
    reqs, rep = validate_stage("requirement-analyst", dirty_reqs)
    check("REQ-1 → REQ-001", reqs[0]["id"] == "REQ-001")
    check("裸数字 2 → REQ-002", reqs[1]["id"] == "REQ-002")
    check("req3 → REQ-003", reqs[2]["id"] == "REQ-003")
    check("非法优先级 critical → P0（高严重度别名）", reqs[1]["priority"] == "P0")
    check("无标题/非对象被丢弃", len(reqs) == 3, f"got {len(reqs)}")
    check("修复计数 >= 3", rep.repaired >= 3, f"got {rep.repaired}")
    check("丢弃计数 == 2", rep.dropped == 2, f"got {rep.dropped}")

    items = reqs  # 后续阶段的引用基准

    # ── 2. project-scout：relevant 布尔化 ──
    print("[2] project-scout")
    scout, rep2 = validate_stage("project-scout", [
        {"name": "baofu-customer-core", "relevant": "true", "reason": "登录实现"},
        {"name": "member-exchange-client", "relevant": False},
        {"name": "", "relevant": True},
    ])
    check("字符串 'true' 布尔化", scout[0]["relevant"] is True)
    check("无名项目丢弃", len(scout) == 2, f"got {len(scout)}")

    # ── 3. code-locator：confidence 钳制 + line 规范 + req_ref 归并 ──
    print("[3] code-locator")
    ev, rep3 = validate_stage("code-locator", [
        {"project": "customer-core", "path": "src/LoginServiceImpl.java", "line": "585",
         "symbol": "checkPwd", "snippet": "...", "confidence": 1.7,
         "requirement_id": "REQ-001"},
        {"project": "customer-core", "path": "src/Other.java", "line": "abc", "confidence": 0.8},
        {"project": "x", "path": "", "confidence": 0.9},   # 无路径丢弃
        {"project": "customer-core", "path": "src/Ghost.java", "confidence": 0.9,
         "requirement_id": "REQ-999"},                     # 幽灵需求引用 → 丢弃
    ], items=items)
    check("行号字符串→int", ev[0]["line"] == 585)
    check("confidence 1.7 钳制到 1.0", ev[0]["confidence"] == 1.0)
    check("req_ref 归并 REQ-001", ev[0]["requirement_id"] == "REQ-001")
    check("无 req_ref 留空不丢", ev[1]["requirement_id"] == "")
    check("无路径丢弃", len(ev) == 3, f"got {len(ev)}")
    # 挂错需求的证据不丢：路径是实查成果，关联清空降级保留
    check("幽灵 req_ref → 证据保留关联清空", ev[2]["requirement_id"] == "" and ev[2]["path"] == "src/Ghost.java")
    # 无需求基准时（早期调用）：req_ref 规范化但不归并
    ev2, _ = validate_stage("code-locator", [
        {"project": "p", "path": "src/A.java", "confidence": 0.5, "requirement_id": "REQ-2"},
    ])
    check("无基准时 req_ref 规范化 REQ-2 → REQ-002", ev2[0]["requirement_id"] == "REQ-002")

    # ── 4. call-chain：risk 枚举 + 无 steps 丢弃 + steps 对象规范化 ──
    print("[4] call-chain")
    chains, rep4 = validate_stage("call-chain", [
        {"name": "登录调用链", "risk": "HIGH",
         "steps": [{"project": "web", "component": "Login.vue", "call": "POST /login"},
                   {"project": "customer-core", "component": "LoginController", "call": "checkPwd()"}]},
        {"name": "混合步骤", "risk": "low", "steps": [{"project": "a", "call": "x()"}, "纯字符串步骤"]},
        {"name": "空链路", "risk": "low", "steps": []},
    ])
    check("risk HIGH → high", chains[0]["risk"] == "high")
    check("steps 对象保留三字段", chains[0]["steps"][0]["project"] == "web"
          and chains[0]["steps"][0]["component"] == "Login.vue"
          and chains[0]["steps"][0]["call"] == "POST /login")
    check("字符串步骤兼容（归入 call）", chains[1]["steps"][1]["call"] == "纯字符串步骤")
    check("无步骤链路丢弃", len(chains) == 2, f"got {len(chains)}")
    # 入库回归：save_impact_scopes 消费对象 steps 不崩（M3.2a 修复的直接动机）
    try:
        joined = ", ".join(dict.fromkeys(
            str(s.get("project", "")) for s in chains[0]["steps"] if s.get("project")))
        check("对象 steps 可入库（project 列拼接）", joined == "web, customer-core", f"got {joined!r}")
    except AttributeError:
        check("对象 steps 可入库（project 列拼接）", False, "s.get 抛 AttributeError——steps 仍是字符串")

    # ── 5. impl-reviewer：fail 无证据降级 + 引用归并 ──
    print("[5] impl-reviewer")
    impl, rep5 = validate_stage("impl-reviewer", [
        {"requirement_id": "REQ-001", "status": "implemented", "verdict": "fail",
         "confidence": 0.9, "evidence_refs": [], "gaps": []},                    # fail 无证据
        {"requirement_id": "REQ-1", "status": "not_found", "verdict": "needs_review",
         "confidence": "0.8", "evidence_refs": ["EV-001"]},                      # 引用 REQ-1 → REQ-001
        {"requirement_id": "REQ-999", "verdict": "pass", "status": "implemented",
         "confidence": 0.9, "evidence_refs": []},                                # 未知需求
        {"requirement_id": "登录密码错误锁定", "status": "implemented", "verdict": "pass",
         "confidence": 0.9, "evidence_refs": []},                                # 标题当 ID → 就近归并
    ], items=items)
    check("fail 无证据 → needs_review", impl[0]["verdict"] == "needs_review")
    check("REQ-1 归并到 REQ-001", impl[1]["requirement_id"] == "REQ-001")
    check("标题当 ID 归并到 REQ-001", impl[2]["requirement_id"] == "REQ-001")
    check("未知 REQ-999 丢弃", len(impl) == 3, f"got {len(impl)}")
    check("confidence 字符串→float", impl[1]["confidence"] == 0.8)

    # ── 6. test-designer：五类枚举 + 引用归并 ──
    print("[6] test-designer")
    cases, rep6 = validate_stage("test-designer", [
        {"requirement_id": "REQ-001", "title": "连续错误5次锁定", "kind": "边界",
         "steps": ["输错5次"], "expected": "账户锁定30分钟"},
        {"requirement_id": "REQ-003", "title": "无预期", "kind": "functional", "expected": ""},
        {"requirement_id": "REQ-999", "title": "引用不存在", "kind": "functional", "expected": "x"},
    ], items=items)
    check("中文类型『边界』→ boundary", cases[0]["kind"] == "boundary")
    check("无预期丢弃", len(cases) == 1, f"got {len(cases)}")

    # ── 7. quality-judge：risk 枚举 + 未知需求丢弃 ──
    print("[7] quality-judge")
    verdicts, rep7 = validate_stage("quality-judge", [
        {"requirement_id": "REQ-002", "risk": "严重", "rationale": "多方式登录",
         "recommendation": "补充回归"},
        {"requirement_id": "REQ-002", "risk": "高", "rationale": "多方式登录",
         "recommendation": "补充回归"},
        {"requirement_id": "REQ-888", "risk": "high", "rationale": "幽灵", "recommendation": "x"},
    ], items=items)
    check("中文别名『严重』→ high", verdicts[0]["risk"] == "high")
    check("中文别名『高』→ high", verdicts[1]["risk"] == "high")
    check("幽灵需求丢弃", len(verdicts) == 2, f"got {len(verdicts)}")

    # ── 8. report-writer：双格式兼容 + 非字符串视角丢弃 ──
    print("[8] report-writer")
    views_a, rep8a = validate_stage("report-writer", {"views": {"dev": "研发视角", "qa": "测试视角", "product": 123}})
    views_b, rep8b = validate_stage("report-writer", {"dev": "研发", "qa": "测试", "product": "产品"})
    check("包裹格式解包", views_a.get("dev") == "研发视角")
    check("非字符串视角丢弃", "product" not in views_a)
    check("裸格式兼容", views_b.get("qa") == "测试")

    # ── 9. 汇总 ──
    print("[9] 边界：None / 非 list / 未知 agent")
    none_res, none_rep = validate_stage("code-locator", None)
    check("None 输入 → None", none_res is None)
    unknown_res, _ = validate_stage("nonexistent-agent", {"x": 1})
    check("未知 agent 原样透传", unknown_res == {"x": 1})
    badlist, _ = validate_stage("code-locator", "not-a-list")
    check("非 list 输入 → None", badlist is None)

    # ── 10. 路由：智能长在 skills/rules 里，代码零关键词（2026-08-25 用户定调）──
    # 问候/闲聊/混合句怎么分，是 intent-classifier 的 system_prompt + skills/routing-rules
    # 里写给模型的规则；代码侧只有「DSH 真不可用时」的极简兜底。本冒烟环境无 DSH，
    # 验证兜底分支 + 注册表 prompt 含问候规则。
    print("[10] 路由（兜底分支 + 规则入 prompt）")
    # 本冒烟环境可能 DSH 在线（node 载体已构建 + 源码可用 → classify 直连模型）。
    # 验证「兜底分支」必须强制 DSH 不可用，否则模型真实回答会让 reason 不含「启发式」。
    import app.services.router as _rt10
    _orig10 = _rt10.dsh_manager.run_turn
    _rt10.dsh_manager.run_turn = lambda p, session_id=None, on_event=None: {
        "status": "fallback", "message": "DSH 未就绪（冒烟强制兜底）"}
    try:
        c1 = classify("你好")
    finally:
        _rt10.dsh_manager.run_turn = _orig10
    check("「你好」兜底 → qa（不进流水线）", c1["intent"] == "qa")
    check("兜底 reason 显式标注启发式", "启发式" in c1.get("reason", ""), f"got {c1.get('reason')!r}")
    check("「你好，我要分析登录需求」兜底 → analyze（不误伤）",
          classify("你好，我要分析登录需求")["intent"] == "analyze")
    check("「全流程…生成报告」兜底 → full", classify("帮我全流程跑一遍生成报告")["intent"] == "full")
    # 2026-09-01：句中问号/疑问词也视为问句（实测「…结论如何？一句话概括」
    # 曾被 endswith 漏判成 analyze，追问被错建分析任务）
    check("句中问号兜底 → qa（追问不误建任务）",
          classify("刚才那个分析任务结论如何？一句话概括")["intent"] == "qa")
    check("疑问词兜底 → qa", classify("如何设计幂等用例")["intent"] == "qa")
    check("无问句特征兜底 → analyze（不误伤）",
          classify("帮我把这个需求结构化分析一下")["intent"] == "analyze")
    a1 = qa_answer("你好")
    # DSH 在线时返回模型真实回答；离线时回退到 _OFFLINE_REPLY。两种环境都合法，
    # 关键不变式：绝不静默空答（至少给一句话），且离线时显式声明未调用 AI。
    check("问答回答非空（在线=模型答 / 离线=能力引导）", bool(a1 and a1.strip()), f"got {a1[:60]!r}")
    # 错误分支确定性验证（打桩，2026-09-01 修复「模型未返回内容」黑盒）：
    # 模型被调了但报错（404/配额/超时）→ 回答说真因 + model_error 信号；
    # 只有 DSH Runtime 真没起来（fallback）才落到「未调用 AI」能力引导。
    import app.services.router as _rt
    _orig_qa = _rt.dsh_manager.run_turn
    _rt.dsh_manager.run_turn = lambda p, session_id=None, on_event=None: {
        "status": "error", "message": "DeepSeek API error (HTTP 404)"}
    try:
        qr = _rt.qa_answer_result("你好")
    finally:
        _rt.dsh_manager.run_turn = _orig_qa
    check("模型报错时回答含真因（404）", "404" in qr["answer"], f"got {qr['answer'][:60]!r}")
    check("模型报错透出 model_error 信号", bool(qr["model_error"]), f"got {qr['model_error']!r}")
    _rt.dsh_manager.run_turn = lambda p, session_id=None, on_event=None: {
        "status": "fallback", "message": "DSH 未就绪"}
    try:
        a_offline = _rt.qa_answer("你好")
    finally:
        _rt.dsh_manager.run_turn = _orig_qa
    check("DSH 未就绪兜底明说未调用 AI", "未调用 AI" in a_offline,
          f"got {a_offline[:60]!r}")
    # 注册表：规则长在 prompt/skill 里
    ic = reg.get_agent("intent-classifier")
    check("intent-classifier prompt 含问候规则", "问候" in ic.system_prompt)
    check("intent-classifier prompt 消歧「问结论=qa」", "问结论" in ic.system_prompt)
    check("intent-classifier 挂 routing-rules skill", getattr(ic, "skill", None) == "routing-rules")
    qa = reg.get_agent("qa-assistant")
    check("qa-assistant prompt 含问候回应规则", "问候" in qa.system_prompt)
    ra = reg.get_agent("requirement-analyst")
    check("requirement-analyst prompt 禁编造占位需求", "编造" in ra.system_prompt or "占位" in ra.system_prompt)
    check("requirement-analyst 挂 requirement-analysis skill", getattr(ra, "skill", None) == "requirement-analysis")

    # ── 11. 路由韧性：模型失败原地重试一次，不轻易降级（2026-08-26）──
    # 铁律「尽可能调起 AI」的工程面：run_turn 首次失败（瞬时故障）应重试，
    # 两次都失败才走启发式兜底。本冒烟通过打桩验证调用计数。
    print("[11] 路由韧性（失败重试一次再兜底）")
    import app.services.router as rt
    calls = {"n": 0}

    def fake_run_turn(prompt, session_id=None, on_event=None):
        calls["n"] += 1
        return {"status": "error", "message": "模拟瞬时故障"}

    orig = rt.dsh_manager.run_turn
    rt.dsh_manager.run_turn = fake_run_turn
    try:
        r1 = rt.classify("帮我分析登录需求")
    finally:
        rt.dsh_manager.run_turn = orig
    check("瞬时故障重试一次（共调 2 次模型）", calls["n"] == 2, f"called {calls['n']}")
    check("两次失败后走启发式兜底", "启发式" in r1.get("reason", ""), f"got {r1.get('reason')!r}")
    # 成功路径只调一次（重试不浪费 token）
    calls["n"] = 0

    def fake_ok(prompt, session_id=None, on_event=None):
        calls["n"] += 1
        return {"status": "ok", "final_response": '{"intent":"qa","confidence":0.9,"reason":"问候"}', "finish_reason": "stop"}

    rt.dsh_manager.run_turn = fake_ok
    try:
        r2 = rt.classify("你好")
    finally:
        rt.dsh_manager.run_turn = orig
    check("成功路径只调一次模型", calls["n"] == 1, f"called {calls['n']}")
    check("模型结果不被兜底覆盖", r2["intent"] == "qa" and r2["reason"] == "问候")

    # ── 12. 多轮会话：每会话独立 DSH 会话 + 历史注入（2026-08-26）──
    # classify/qa_answer 带 conversation_id 时：DSH session 为 conv-xxx--router，
    # 且提示词注入会话历史摘要（DB 不可用时纯靠 DSH 会话记忆，注入块为空不崩）。
    print("[12] 多轮会话（conversation 路由）")
    seen_prompts: list[str] = []
    seen_sessions: list[str] = []

    def fake_multi(prompt, session_id=None, on_event=None):
        seen_prompts.append(prompt)
        seen_sessions.append(session_id)
        return {"status": "ok",
                "final_response": '{"intent":"qa","confidence":0.9,"reason":"追问承接"}',
                "finish_reason": "stop"}

    rt.dsh_manager.run_turn = fake_multi
    try:
        rt.classify("那它支持幂等吗", conversation_id="abc")  # conv_id 不含 conv- 前缀
        rt.qa_answer("那它支持幂等吗", conversation_id="abc")
        rt.classify("你好")  # 无会话 → 全局路由会话
    finally:
        rt.dsh_manager.run_turn = orig
    # 2026-08-27 修复：classify 与 qa_answer 是不同 Agent，不能共用一条 DSH 会话——
    # 第一回合把会话定型成意图分类器（输出 JSON），第二回合塞 qa prompt 进去会被
    # 上下文污染，模型易续写 JSON 导致 final_response 为空（"模型未返回内容"）。
    # 现在按 Agent 分会话：classify→conv-xxx--intent，qa→conv-xxx--qa。
    check("classify 用 conv-xxx--intent 会话",
          seen_sessions[0] == "conv-abc--intent", f"got {seen_sessions[0]!r}")
    check("qa 用 conv-xxx--qa 会话（与 classify 分离）",
          seen_sessions[1] == "conv-abc--qa", f"got {seen_sessions[1]!r}")
    check("无会话 classify 回退 router-global--intent", seen_sessions[2] == "router-global--intent")
    check("提示词含意图分类规则", "意图分类器" in seen_prompts[0])
    check("提示词含问答规则", "助手" in seen_prompts[1])

    # ── 13. Agent 注册表：skill 挂载与 prompt 契约收紧（2026-08-26）──
    print("[13] Agent 逐个优化断言")
    check("test-designer 挂 test-design skill", getattr(reg.get_agent("test-designer"), "skill", None) == "test-design")
    check("impl-reviewer 挂 java-code-review skill", getattr(reg.get_agent("impl-reviewer"), "skill", None) == "java-code-review")
    from pathlib import Path as _P
    skills_root = _P(__file__).resolve().parent.parent / "skills"
    for name in ("test-design", "java-code-review", "vue-code-review"):
        check(f"skills/{name}/SKILL.md 存在且非空",
              (skills_root / name / "SKILL.md").exists()
              and (skills_root / name / "SKILL.md").stat().st_size > 200)
    check("code-locator prompt 要求 requirement_id 标注",
          "requirement_id" in reg.get_agent("code-locator").system_prompt)
    check("impl-reviewer prompt 写明四档 status 判定",
          "implemented=" in reg.get_agent("impl-reviewer").system_prompt)
    check("intent-classifier prompt 含多轮追问规则",
          "追问" in reg.get_agent("intent-classifier").system_prompt)

    # ── 14. 校验差重问判定：_validation_is_poor 阈值（2026-08-26）──
    print("[14] requirement-analyst 校验失败重问判定")
    from app.services.orchestrator import _validation_is_poor
    good = ValidationReport(); good.total = 3; good.valid = 3
    check("全原样通过 → 不重问", not _validation_is_poor([{"id": "REQ-001"}], good))
    empty = ValidationReport()  # 空输出：报告干净但没条目
    check("空输出 → 重问确认一次", _validation_is_poor(None, empty))
    all_dropped = ValidationReport(); all_dropped.dropped = 3
    check("全部丢弃 → 重问", _validation_is_poor(None, all_dropped))
    mixed = ValidationReport(); mixed.total = 3; mixed.valid = 1; mixed.repaired = 2
    check("部分修复通过 → 不重问", not _validation_is_poor([{"id": "REQ-001"}], mixed))
    all_bad = ValidationReport(); all_bad.total = 3; all_bad.repaired = 2; all_bad.dropped = 1
    check("无一条原样合法 → 重问", _validation_is_poor([{"id": "REQ-001"}], all_bad))

    # ── 15. 子代理赋能：主理 Agent 身份 + 委派触发点 + agent-collaboration skill ──
    # 2026-08-26 用户要求「agent 能力不足可以子代理去弥补」——每个流水线 Agent
    # 成为该阶段主理（对契约输出全权负责），能力不足时按 fork/spawn 委派再合成。
    # 路由层 2 个 Agent 轻量，单回合直出，不强制委派。
    print("[15] 子代理赋能（主理 Agent + 委派触发点）")
    collab_skill = _P(__file__).resolve().parent.parent / "skills" / "agent-collaboration" / "SKILL.md"
    check("agent-collaboration skill 存在且非空",
          collab_skill.exists() and collab_skill.stat().st_size > 500,
          f"got exists={collab_skill.exists()}")
    # 8 个流水线 Agent 都升级为主理 + 含委派触发点
    pipeline_ids = ["requirement-analyst", "project-scout", "code-locator", "call-chain",
                    "impl-reviewer", "test-designer", "quality-judge", "report-writer"]
    delegation_keywords = ("子代理", "fork", "spawn")
    for aid in pipeline_ids:
        a = reg.get_agent(aid)
        sp = a.system_prompt
        check(f"{aid} 是主理 Agent（含『主理』）", "主理" in sp, f"prompt 首句缺主理身份")
        check(f"{aid} 含委派触发点（fork/spawn/子代理）",
              any(k in sp for k in delegation_keywords),
              f"prompt 无委派触发点")
        check(f"{aid} 引用 agent-collaboration skill 合成纪律",
              "agent-collaboration" in sp, "未引用协作 skill")
        check(f"{aid} 强调最终契约由自己合成",
              "合成" in sp or "输出全权负责" in sp, "未声明合成权不下放")
    # 路由层不强制委派
    ic_sp = reg.get_agent("intent-classifier").system_prompt
    qa_sp = reg.get_agent("qa-assistant").system_prompt
    check("intent-classifier 声明轻量不委派",
          "轻量" in ic_sp and "不委派子代理" in ic_sp)
    check("qa-assistant 声明轻量不委派",
          "轻量" in qa_sp and "不委派子代理" in qa_sp)
    # 活动流能捕获 subagent_fork / subagent 工具调用（_activity_handler 内部走
    # _push_activity，写入 _activity[task_id]，断言从该表读）
    from app.services.orchestrator import _activity_handler, _activity, _act_seq
    _activity.pop("t-sub", None)
    _act_seq.pop("t-sub", None)
    h = _activity_handler("t-sub", "code-locator")
    h({"type": "tool/call", "data": {"name": "subagent_fork",
       "arguments": {"prompt": "查 customer-core 的登录实现"}}})
    h({"type": "tool/call", "data": {"name": "subagent",
       "arguments": {"prompt": "追会员登录链路"}}})
    acts = _activity.get("t-sub", [])
    tools = [a.get("tool") for a in acts]
    details = " ".join(str(a.get("detail", "")) for a in acts)
    check("fork 工具调用进活动流", "subagent_fork" in tools, f"got {tools}")
    check("spawn 工具调用进活动流", "subagent" in tools, f"got {tools}")
    check("活动流 detail 含委派 prompt", "登录" in details, f"got {details[:120]!r}")

    # ── 16. 会话删除：级联 chat_messages + 会话内任务及其衍生七表（2026-08-27）──
    # 用户要求「会话支持删除」。删除一个会话要连带删：该会话的全部消息 +
    # 会话内挂的每个任务 + 每个任务的衍生数据（requirements/code_evidence/...
    # /agent_sessions/dsh_events）。delete_task 正交清七表。
    print("[16] 会话删除（级联消息 + 任务 + 衍生数据）")
    from app.db import entities as E2
    from app.db.engine import init_schema

    init_schema()  # 建表幂等（含 [23] 的 app_settings；表已存在则跳过）
    _now = E2._now  # noqa: SLF001 — 复用 entities 的时间戳生成
    # 建一个有消息+有任务的会话
    cid = E2.create_conversation("删除测试会话")
    E2.save_message(cid, "user", "帮我分析登录")
    tid = "smoke-del-task-001"
    # 先确保任务行存在（直接 insert，绕过 create_task 的异步编排）。
    # 用先 DELETE 再 INSERT 的方言中性写法替代 INSERT OR IGNORE（MySQL 不认 OR IGNORE）。
    E2.engine.execute(
        "DELETE FROM analysis_tasks WHERE task_id = ?",
        (tid,))
    E2.engine.insert(
        "INSERT INTO analysis_tasks (task_id, title, source_text, projects, branch, "
        "workspace, status, created_at, updated_at) VALUES (?, ?, '', '', '', '', 'completed', ?, ?)",
        (tid, "删除测试任务", _now(), _now()))
    E2.save_message(cid, "assistant", "已创建分析任务", intent="analyze", task_id=tid)
    # 给任务塞衍生数据（requirements 代表，验证级联）
    E2.save_requirements(tid, [{"id": "REQ-001", "title": "登录锁定", "priority": "P0",
                                "description": "", "acceptance_criteria": ["连续错误5次锁定"]}])
    check("删除前会话存在", E2.get_conversation(cid) is not None)
    check("删除前消息存在", len(E2.list_messages(cid)) == 2)
    check("删除前任务衍生数据存在", len(E2.list_requirements(tid)) == 1)

    res = E2.delete_conversation(cid)
    check("delete_conversation 返回 existed=True", res["existed"])
    check("delete_conversation 返回级联任务清单", tid in res["deleted_tasks"])
    check("删除后会话不存在", E2.get_conversation(cid) is None)
    check("删除后消息清空", len(E2.list_messages(cid)) == 0)
    check("删除后任务衍生数据级联清空", len(E2.list_requirements(tid)) == 0)
    check("删除后任务行级联清空", E2.get_task(tid) is None)

    # 删不存在的会话：existed=False，不报错
    res2 = E2.delete_conversation("no-such-conv")
    check("删不存在会话 existed=False 不崩", res2["existed"] is False)

    # delete_task 正交：单独删任务清七表（独立于会话）
    tid2 = "smoke-del-task-002"
    E2.engine.execute("DELETE FROM analysis_tasks WHERE task_id = ?", (tid2,))
    E2.engine.insert(
        "INSERT INTO analysis_tasks (task_id, title, source_text, projects, branch, "
        "workspace, status, created_at, updated_at) VALUES (?, ?, '', '', '', '', 'completed', ?, ?)",
        (tid2, "正交删除测试", _now(), _now()))
    E2.save_requirements(tid2, [{"id": "REQ-001", "title": "x", "priority": "P1",
                                  "description": "", "acceptance_criteria": []}])
    E2.save_code_evidence(tid2, [{"project": "p", "path": "src/A.java", "line": 1,
                                  "symbol": "x", "snippet": "", "confidence": 0.5,
                                  "requirement_id": ""}])
    ok = E2.delete_task(tid2)
    check("delete_task 返回 True", ok is True)
    check("delete_task 级联清 requirements", len(E2.list_requirements(tid2)) == 0)
    check("delete_task 级联清 code_evidence", len(E2.list_code_evidence(tid2)) == 0)
    check("delete_task 清任务行", E2.get_task(tid2) is None)
    ok2 = E2.delete_task("never-existed")
    check("delete_task 删不存在返回 False", ok2 is False)

    # ── 17. 项目传参：选了项目，问答/意图也要带上（2026-08-27）──
    # 用户报「选了项目传参不带，怎么基于哪个项目提问」。修复：前端把 selProjects
    # 透传到 /api/chat，后端 classify/qa_answer 都接 projects 参数，并注入
    # 「用户选定的目标项目」段到提示词，让模型把回答落到具体项目上。
    print("[17] 项目传参（classify/qa_answer 注入目标项目）")
    import app.services.router as rt2
    seen_p2: list[str] = []

    def fake_proj(prompt, session_id=None, on_event=None):
        seen_p2.append(prompt)
        return {"status": "ok",
                "final_response": '{"intent":"qa","confidence":0.9,"reason":"项目问答"}',
                "finish_reason": "stop"}

    orig2 = rt2.dsh_manager.run_turn
    rt2.dsh_manager.run_turn = fake_proj
    try:
        rt2.classify("这个项目怎么测", projects=["customer-core", "admin-core"])
        rt2.qa_answer("这个项目怎么测", projects=["customer-core"])
        rt2.classify("你好")  # 不带项目 → 注入块应为空
    finally:
        rt2.dsh_manager.run_turn = orig2
    check("classify 带 projects 时提示词含目标项目",
          "目标项目" in seen_p2[0] and "customer-core" in seen_p2[0],
          f"got {seen_p2[0][-120:]!r}")
    check("qa_answer 带 projects 时提示词含目标项目",
          "目标项目" in seen_p2[1] and "customer-core" in seen_p2[1],
          f"got {seen_p2[1][-120:]!r}")
    check("无 projects 时不注入目标项目段",
          "目标项目" not in seen_p2[2], f"got {seen_p2[2][-120:]!r}")

    # /api/chat 端点签名接 projects 并回传
    from app.api import requirements as api_req
    import inspect
    sig = inspect.signature(api_req.chat)
    check("/api/chat 签名含 projects 参数", "projects" in sig.parameters,
          f"got params={list(sig.parameters)}")

    # ── 18. 问答流式 + 附件并入提问（2026-08-27 第二轮）──
    # ① qa_answer(on_delta=...) 收 DSH assistant/message 事件文本段；
    # ② /api/chat 文本附件内容并入提问（附件-only 不再被整包丢弃）；
    # ③ /api/chat/stream SSE 端点存在且签名含同参数。
    print("[18] 问答流式 + 附件并入提问")
    seen_events: list[dict] = []

    def fake_stream(prompt, session_id=None, on_event=None):
        seen_events.append({"prompt": prompt, "has_cb": on_event is not None})
        # 模拟 DSH 推两段 assistant/message
        if on_event is not None:
            on_event({"type": "assistant/message", "data": {"message": {
                "content": [{"type": "text", "text": "登录测试建议："}]}}})
            on_event({"type": "assistant/message", "data": {"message": {
                "content": [{"type": "text", "text": "覆盖五种登录方式与锁定。"}]}}})
            on_event({"type": "tool/call", "data": {"name": "grep"}})  # 非文本事件应被忽略
        return {"status": "ok", "final_response": "登录测试建议：覆盖五种登录方式与锁定。",
                "finish_reason": "stop"}

    orig3 = rt2.dsh_manager.run_turn
    rt2.dsh_manager.run_turn = fake_stream
    deltas: list[str] = []
    try:
        ans = rt2.qa_answer("怎么测登录", projects=["customer-core"],
                            on_delta=lambda c: deltas.append(c))
    finally:
        rt2.dsh_manager.run_turn = orig3
    check("qa_answer on_delta 收到 2 段文本", len(deltas) == 2, f"got {deltas}")
    check("qa_answer on_delta 过滤非文本事件", all("grep" not in d for d in deltas))
    check("qa_answer 流式回调不影响最终回答", "登录测试" in ans, f"got {ans[:50]!r}")
    check("qa_answer 无回调时等价于普通回合", seen_events[0]["has_cb"] is True)

    sig2 = inspect.signature(api_req.chat)
    check("/api/chat 签名含 attachments 参数", "attachments" in sig2.parameters,
          f"got params={list(sig2.parameters)}")
    check("/api/chat/stream 端点已注册", hasattr(api_req, "chat_stream"))

    # ── 19. 输入保真：chat_stream 也接 attachments；文本附件合并逻辑统一 ──
    # （2026-08-30：用户报「再检查一遍输入场景的失真」——chat_stream 此前
    # 完全不接 attachments，前端走流式主链路时附件整包丢失。）
    print("[19] 输入保真（chat_stream 附件 + 合并函数）")
    sig3 = inspect.signature(api_req.chat_stream)
    check("/api/chat/stream 签名含 attachments 参数", "attachments" in sig3.parameters,
          f"got params={list(sig3.parameters)}")

    import asyncio as _asyncio

    # _merge_text_attachments：文本附件并入、二进制计数、截断上限
    class _FakeUpload:
        def __init__(self, filename: str, data):
            self.filename = filename
            self._data = data

        async def read(self):
            return self._data

    merge = api_req._merge_text_attachments
    t1, b1 = _asyncio.run(merge("帮我分析", [
        _FakeUpload("req.md", "需求：登录锁定规则".encode("utf-8"))]))
    check("文本附件内容并入提问", "需求：登录锁定规则" in t1 and t1.startswith("帮我分析"), f"got {t1!r}")
    check("文本附件二进制计数为 0", b1 == 0)
    t2, b2 = _asyncio.run(merge("", [_FakeUpload("shot.png", b"\x89PNG" + b"\x00" * 8)]))
    check("纯图片附件：文本为空、计数 1", t2 == "" and b2 == 1, f"got {t2!r}, {b2}")
    t3, b3 = _asyncio.run(merge("看下这个", [
        _FakeUpload("a.txt", b"x" * 9000)]))
    check("文本附件超长截断到 4000", len(t3.split("[附件 a.txt]\n", 1)[1]) == 4000, f"got {len(t3)}")
    check("文本+图片混合：图片计数 1", b3 == 0)
    t4, b4 = _asyncio.run(merge("", [
        _FakeUpload("a.md", "A".encode("utf-8")),
        _FakeUpload("b.png", b"\x89PNG"),
        _FakeUpload("c.txt", "C".encode("utf-8"))]))
    check("多附件按类型分流（文本并入、图片计数）",
          "A" in t4 and "C" in t4 and b4 == 1, f"got {t4!r}, {b4}")

    # ── 20. Agent 间上下文传递（digest 保真：显式截断 + 证据带原文） ──────
    # （2026-08-31：用户要求「优化输入+输出整个流程」——审查发现三处失真：
    #  ① requirement digest limit=12 静默丢第 13+ 条需求；② evidence digest
    #  不带 snippet（审查 Agent 拿不到代码原文）；③ call-chain/test-designer/
    #  quality-judge 缺上游产物输入。本节验证 digest 层的行为。）
    print("[20] Agent 间上下文传递（digest 保真）")
    from app.services.orchestrator import _requirement_digest as _rd, _evidence_digest as _ed

    many = [{"id": f"REQ-{i:03d}", "title": f"需求{i}", "priority": "P1",
             "description": "描述", "acceptance_criteria": ["验收"]} for i in range(1, 16)]
    d15 = _rd(many)
    check("digest 超 12 条显式注明溢出", "另有 3 条需求未列出" in d15, f"got tail {d15[-80:]!r}")
    check("digest 溢出标注含后续起点 ID", "REQ-013" in d15)
    d8 = _rd(many[:8])
    check("digest 未溢出无标注", "未列出" not in d8)
    d12 = _rd(many[:12])
    check("digest 恰好 12 条无标注（边界）", "未列出" not in d12 and "REQ-012" in d12)

    evs = [{"project": "core", "path": "src/Login.java", "line": 5, "symbol": "checkPwd",
            "confidence": 0.9, "summary": "if (errorNum >= 4) { lock(60); }"},
           {"project": "core", "path": "src/A.java", "line": 1, "symbol": "",
            "confidence": 0.5, "summary": ""}]
    ed = _ed(evs)
    check("证据 digest 带代码原文片段", "errorNum >= 4" in ed, f"got {ed!r}")
    check("证据 digest 空 snippet 不留悬挂标注", "代码：" not in ed.split("src/A.java")[1][:40])
    ed20 = _ed([{"project": "p", "path": f"f{i}.java", "line": i, "symbol": "",
                 "confidence": 0.5, "summary": "x"} for i in range(20)])
    check("证据 digest 超 15 条显式注明溢出", "另有 5 处证据未列出" in ed20)

    # ── 21. 任务结论回写会话（输出侧记忆闭环：追问「刚才结论如何」有据可答） ──
    print("[21] 任务结论回写会话")
    from app.services.orchestrator import _notify_conversation as _notify
    cid5 = E2.create_conversation("回写测试会话")
    tid5 = "smoke-notify-task-001"
    E2.engine.execute("DELETE FROM analysis_tasks WHERE task_id = ?", (tid5,))
    E2.engine.insert(
        "INSERT INTO analysis_tasks (task_id, title, source_text, projects, branch, "
        "workspace, status, created_at, updated_at) VALUES (?, ?, '', '', '', '', 'completed', ?, ?)",
        (tid5, "回写测试任务", _now(), _now()))
    E2.save_message(cid5, "assistant", "已创建分析任务", intent="full", task_id=tid5)
    check("反查任务所属会话（chat_messages.task_id）",
          E2.find_conversation_of_task(tid5) == cid5)
    _notify(tid5, "分析任务完成：3 条需求、5 处证据，高风险 1 条。可直接追问结论细节。")
    msgs5 = E2.list_messages(cid5)
    check("结论回写进会话消息流",
          any("分析任务完成：3 条需求" in m["content"] for m in msgs5),
          f"got {[m['content'][:30] for m in msgs5]}")
    check("回写消息带 task_id 关联（前端渲染为可点击任务块）",
          any(m.get("task_id") == tid5 and "分析任务完成" in m["content"] for m in msgs5))
    _notify("no-such-task-anywhere", "不应写入")
    check("无会话关联的任务回写静默跳过不崩", True)
    E2.delete_conversation(cid5)

    # ── 22. 模型级错误显式化（2026-09-01「模型未返回内容」黑盒修复） ──────
    # SDK 的 run() 不因模型错误抛异常——404/配额/超时表现为 finish_reason=error
    # + final_response=""，此前被当成 status=ok 返回空串，真因完全不可见。
    print("[22] run_turn 模型错误显式化")
    from app.dsh import runtime as dshrt

    class FakeResult:
        def __init__(self, final: str, finish: str, events: list):
            self.session_id = "smoke-fake-session"
            self.final_response = final
            self.finish_reason = finish
            self.events = events

    ERR_EVENTS = [{"type": "turn/end", "data": {"reason": {
        "kind": "error",
        "error": {"message": "DeepSeek API error (HTTP 404)", "code": "HTTP_404", "status": 404}}}}]

    class FakeHarness:
        def __init__(self, result):
            self._r = result

        def run(self, prompt, session_id=None, on_notification=None):
            return self._r

    m22 = dshrt.manager
    orig_h = m22._harness
    m22._harness = FakeHarness(FakeResult("", "error", ERR_EVENTS))
    try:
        r22 = m22.run_turn("ping", session_id="smoke-err")
        check("模型 404 → status=error（不再伪装 ok）",
              r22.get("status") == "error", f"got {r22.get('status')!r}")
        check("404 真因透出到 message", "404" in str(r22.get("message", "")),
              f"got {r22.get('message')!r}")
        m22._harness = FakeHarness(FakeResult("", "completed", []))
        r22b = m22.run_turn("ping", session_id="smoke-err")
        check("空 final_response（finish=completed）也判错误",
              r22b.get("status") == "error", f"got {r22b.get('status')!r}")
        m22._harness = FakeHarness(FakeResult("正常回答", "completed", []))
        r22c = m22.run_turn("ping", session_id="smoke-err")
        check("正常回答仍 status=ok",
              r22c.get("status") == "ok" and r22c.get("final_response") == "正常回答",
              f"got {r22c.get('status')!r}")
    finally:
        m22._harness = orig_h
    # classify 的兜底 reason 说真话（不再一律「DSH 不可用」）
    import app.services.router as rt22
    orig22 = rt22.dsh_manager.run_turn
    rt22.dsh_manager.run_turn = lambda p, session_id=None, on_event=None: {
        "status": "error", "message": "DeepSeek API error (HTTP 404)"}
    try:
        r22d = rt22.classify("帮我分析登录需求")
    finally:
        rt22.dsh_manager.run_turn = orig22
    check("classify 兜底 reason 标注模型调用失败真因",
          "模型调用失败" in r22d.get("reason", "") and "404" in r22d.get("reason", ""),
          f"got {r22d.get('reason')!r}")
    # base_url 归一化：DSH 请求 {baseURL}/chat/completions，纯域名网关需补 /v1
    nb = dshrt.manager._normalize_base_url
    check("base_url 纯域名自动补 /v1",
          nb("https://ai-api.baoyun.com") == "https://ai-api.baoyun.com/v1",
          f"got {nb('https://ai-api.baoyun.com')!r}")
    check("base_url 已带 /v1 保持原样",
          nb("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1")
    check("base_url 自定义路径尊重原样",
          nb("https://gw.example.com/api") == "https://gw.example.com/api")
    check("base_url 尾斜杠清理后补 /v1",
          nb("https://x.com/") == "https://x.com/v1")
    # max_tokens 网关钳制（2026-09-02 宝云 400 修复）：DSH 默认 256000 超网关上限
    mt = dshrt.manager._max_tokens_for
    check("宝云网关 max_tokens 钳制 131072",
          mt("https://ai-api.baoyun.com/v1") == 131072,
          f"got {mt('https://ai-api.baoyun.com/v1')!r}")
    check("官方 API 不钳制（保持 SDK 默认）",
          mt("https://api.deepseek.com/v1") is None,
          f"got {mt('https://api.deepseek.com/v1')!r}")
    check("无 base_url 不钳制", mt(None) is None)
    check("未知网关不钳制（不误伤）",
          mt("https://gw.example.com/v1") is None)

    # ── 23. 模型选型持久化（2026-09-01 修「重启后选型回默认」） ─────────────
    # app_settings 键值对 + manager 懒加载/落库；reconfigure 支持 provider/model
    # 分开换；_resolve_provider_config 优先用持久化的供应商×模型组合。
    print("[23] 模型选型持久化")
    from app.db import entities as E3

    E3.set_setting("smoke_key", "smoke_value")
    check("set/get_setting 读写一致", E3.get_setting("smoke_key") == "smoke_value")
    E3.set_setting("smoke_key", "smoke_value_2")  # upsert 路径
    check("set_setting 二次写入为更新（upsert）",
          E3.get_setting("smoke_key") == "smoke_value_2")
    check("get_setting 未设键返回默认", E3.get_setting("no_such_key", "dft") == "dft")
    m23 = dshrt.manager
    default_row = E3.get_default_model_config() or {}
    def_key = default_row.get("provider_key")
    def_model = (default_row.get("model_ids") or ["deepseek-v4-flash"])[0]
    m23._selection_loaded = False
    m23._preferred_provider_key = None
    m23._preferred_model = None
    m23._load_selection()
    check("懒加载不崩且标记置位", m23._selection_loaded is True)
    # reconfigure 只换模型（不换供应商）——changed 含 model。
    # 强制清内存模型选择（懒加载可能已带出历史持久化值，使切换成 no-op）
    m23.reconfigure(provider_key=def_key)  # 先固定供应商（清掉历史残留选择）
    m23._preferred_model = None
    out23 = m23.reconfigure(model=def_model)
    check("reconfigure(model=...) changed 含 model", "model" in out23.get("changed", []),
          f"got {out23.get('changed')}")
    check("模型选择已持久化", E3.get_setting(m23.ACTIVE_MODEL_KEY) == def_model,
          f"got {E3.get_setting(m23.ACTIVE_MODEL_KEY)!r}")
    check("供应商选择未被模型切换覆盖",
          E3.get_setting(m23.ACTIVE_PROVIDER_KEY) == def_key)
    # 新进程模拟：清内存重载应恢复持久化选择
    m23._selection_loaded = False
    m23._preferred_provider_key = None
    m23._preferred_model = None
    m23._load_selection()
    check("重启模拟：懒加载恢复持久化模型", m23._preferred_model == def_model,
          f"got {m23._preferred_model!r}")
    check("重启模拟：懒加载恢复持久化供应商", m23._preferred_provider_key == def_key,
          f"got {m23._preferred_provider_key!r}")
    # 换供应商时模型不在新目录 → 清掉由目录首个顶上（_resolve 校正）。
    # 不硬编码供应商名（环境相关）：从 DB 取一个 ≠ 当前的启用配置。
    all_cfgs = E3.list_model_configs()
    other = next((c for c in all_cfgs if c.get("enabled") and c.get("provider_key") != def_key), None)
    if other is not None:
        m23.reconfigure(provider_key=other["provider_key"])
        cfg23 = m23._resolve_provider_config() or {}
        check("换供应商后模型回落该供应商目录首个",
              cfg23.get("model_id") == (other.get("model_ids") or [None])[0],
              f"got {cfg23.get('model_id')!r}")
        check("选中供应商已持久化",
              E3.get_setting(m23.ACTIVE_PROVIDER_KEY) == other["provider_key"])
    else:
        check("（环境仅一个供应商，跳过换供应商分支）", True)
    # 还原：切回默认配置 + 其首个模型
    m23.reconfigure(provider_key=def_key, model=(default_row.get("model_ids") or [None])[0])
    cfg23b = m23._resolve_provider_config() or {}
    check("还原默认后解析回默认模型",
          cfg23b.get("model_id") == (default_row.get("model_ids") or [None])[0],
          f"got {cfg23b.get('model_id')!r}")

    # ── 24. DSH 会话物理 ID 隔离（2026-09-02 修 persisted log collision） ────
    # 后端重启/Runtime 重建后，若仍用同一逻辑 ID 新建 live session，DSH
    # persistence coordinator 会拒绝（旧日志 seed 不匹配）。Runtime 内部把
    # 逻辑 ID 映射成 runtime-scoped 物理 ID：同代际同逻辑→同物理（多轮上下文
    # 保留）；stop/重建后代际变更→新物理 ID，不再撞旧 .dsh-sessions 日志。
    print("[24] DSH 会话物理 ID 隔离")
    from app.dsh import runtime as dshrt24

    m24 = dshrt24.manager
    # 捕获 run_turn 喂给 SDK 的物理 session_id（打桩 harness.run）
    seen_pids: list[str | None] = []

    class FakeHarness24:
        def __init__(self):
            self.session_counter = 0

        def run(self, prompt, session_id=None, on_notification=None):
            seen_pids.append(session_id)
            sid = session_id or f"fake-{self.session_counter}"

            class R:
                pass
            r = R()
            r.session_id = sid
            r.final_response = "ok"
            r.finish_reason = "completed"
            r.events = []
            self.session_counter += 1
            return r

        def start(self):
            pass

        def close(self):
            pass

    orig_h24 = m24._harness
    orig_gen24 = m24._runtime_gen
    orig_map24 = m24._session_map
    m24._harness = None  # 强制走 start() 路径生成新代际
    # 注入 fake harness：跳过真实 start()，直接置入并模拟代际生成
    m24._harness = FakeHarness24()
    m24._runtime_gen = "gen1aaa"
    m24._session_map = {}
    try:
        logical = "conv-41ee56477b10--qa"
        # 同一代际、同一逻辑 ID 两次调用 → 同一物理 ID（多轮上下文保留）
        m24.run_turn("ping", session_id=logical)
        m24.run_turn("ping2", session_id=logical)
        check("同代际同逻辑→同物理 ID（多轮稳定）",
              seen_pids[0] == seen_pids[1] and seen_pids[0] is not None,
              f"got {seen_pids[:2]}")
        check("物理 ID ≠ 逻辑 ID（不撞业务 ID 旧日志）",
              seen_pids[0] != logical, f"got {seen_pids[0]!r}")
        check("物理 ID 带代际前缀 r{gen}",
              seen_pids[0].startswith("rgen1aaa-"), f"got {seen_pids[0]!r}")
        # 不同逻辑 ID → 不同物理 ID（intent/qa 隔离）
        m24.run_turn("ping", session_id="conv-41ee56477b10--intent")
        check("不同逻辑→不同物理 ID（intent/qa 隔离）",
              seen_pids[2] != seen_pids[0], f"got intent={seen_pids[2]!r} qa={seen_pids[0]!r}")
        # 模拟 Runtime 重建（stop/异常）：代际变更 → 新物理 ID，不撞旧日志
        m24.stop()  # 清代际与映射
        m24._harness = FakeHarness24()
        m24._runtime_gen = "gen2bbb"
        m24._session_map = {}
        m24.run_turn("ping", session_id=logical)
        check("重建后同逻辑→新物理 ID（不再撞旧持久化日志）",
              seen_pids[3] != seen_pids[0], f"got old={seen_pids[0]!r} new={seen_pids[3]!r}")
        check("新物理 ID 带新代际前缀",
              seen_pids[3].startswith("rgen2bbb-"), f"got {seen_pids[3]!r}")
        # 无 session_id → 透传 None（沿用 SDK 原有随机行为，不强行映射）
        m24.run_turn("one-shot")
        check("无逻辑 ID → 透传 None（SDK 随机 session）",
              seen_pids[4] is None, f"got {seen_pids[4]!r}")
    finally:
        m24._harness = orig_h24
        m24._runtime_gen = orig_gen24
        m24._session_map = orig_map24

    # ── 25. AI-first 编排：requirement-analyst 成功时不跑规则分析 ──────────
    # 2026-09-02 调整：文档语义由 AI 处理，规则只在 Agent 拿不到结构化需求时保底。
    # 打桩 _run_agent 成功 → 不应调用 _run_rule_analysis / NavigatorAnalyzer。
    print("[25] AI-first 编排（Agent 成功不跑规则分析）")
    from app.services import orchestrator as orch25
    import app.services.router as rt25

    seen_rule: list[str] = []

    def fake_run_agent_ok(task_id, agent_id, payload, items=None):
        class S:
            pass
        class VR:
            def summary(self): return "ok"
            def __init__(self): self.repaired = 0; self.dropped = 0; self.total = 2; self.valid = 2
        items_out = [{"id": "REQ-001", "title": "AI 拆的需求", "description": "AI 结构化",
                       "priority": "P1", "acceptance_criteria": ["验收1"]},
                      {"id": "REQ-002", "title": "第二条", "description": "d",
                       "priority": "P2", "acceptance_criteria": []}]
        return items_out, {"final_response": "..."}, VR()

    orig_ra = orch25._run_agent
    orig_rule = orch25._run_rule_analysis
    orig_rt25 = rt25.dsh_manager.run_turn
    # /tasks 端点用 router.classify，但 _run_task 直接用 _run_agent/_run_rule_analysis
    orch25._run_agent = fake_run_agent_ok
    def fake_rule(*a, **kw):
        seen_rule.append("called")
        raise AssertionError("规则分析不应在 AI 成功时执行")
    orch25._run_rule_analysis = fake_rule
    # 让后续 project-scout 等阶段也走 fake（避免真实 DSH 调用）
    def fake_agent_any(task_id, agent_id, payload, items=None):
        return [], {"final_response": ""}, ValidationReport()
    # 只让 requirement-analyst 走 ok 路径，其余阶段返回空（跳过）
    def dispatch(task_id, agent_id, payload, items=None):
        if agent_id == "requirement-analyst":
            return fake_run_agent_ok(task_id, agent_id, payload, items)
        return [], {"final_response": ""}, ValidationReport()
    orch25._run_agent = dispatch
    try:
        tid25 = f"smoke-aifirst-{uuid4().hex[:6]}"
        from app.db import entities as E25
        from app.db.engine import init_schema
        init_schema()
        E25.engine.execute("DELETE FROM analysis_tasks WHERE task_id = ?", (tid25,))
        E25.engine.insert(
            "INSERT INTO analysis_tasks (task_id, title, source_text, projects, branch, "
            "workspace, status, created_at, updated_at) VALUES (?, ?, ?, '', '', '', 'pending', ?, ?)",
            (tid25, "AI-first 测试", "一些需求文本", _now(), _now()))
        orch25._run_task(tid25, "analyze")
        check("AI 成功时不执行 _run_rule_analysis", seen_rule == [],
              f"规则分析被调用 {len(seen_rule)} 次")
        task25 = E25.get_task(tid25)
        check("AI 成功路径产出了报告 ID", bool(task25.get("report_id")),
              f"got {task25.get('report_id')!r}")
        reqs25 = E25.list_requirements(tid25)
        check("需求来自 AI（requirement-analyst），非规则拆分",
              any(r.get("title") == "AI 拆的需求" for r in reqs25),
              f"got {[r.get('title') for r in reqs25]}")
        # 活动流应显示 AI 需求分析，而非「规则分析」作为主路径
        acts = orch25.activity_items(tid25)
        stages = [a.get("stage") for a in acts if a.get("stage")]
        check("活动流无 rule-analysis 作为首阶段", "rule-analysis" not in stages[:1],
              f"got stages={stages}")
    finally:
        orch25._run_agent = orig_ra
        orch25._run_rule_analysis = orig_rule
        rt25.dsh_manager.run_turn = orig_rt25

    print(f"\n结果：{PASS} PASS / {FAIL} FAIL")

    print(f"\n结果：{PASS} PASS / {FAIL} FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
