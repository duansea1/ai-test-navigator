"""M2.3 冒烟：Agent 输出强校验层（agent_validation.py）离线验证。

不依赖 DSH / DB / 网络——直接喂脏数据（模拟 deepseek-v4-flash 的真实漂移风格），
断言：规范化、修复计数、丢弃计数、fail 无证据降级、引用归并。

运行：python scripts/smoke-agents.py
"""
from __future__ import annotations

import sys
from pathlib import Path

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
    c1 = classify("你好")
    check("「你好」兜底 → qa（不进流水线）", c1["intent"] == "qa")
    check("兜底 reason 显式标注启发式", "启发式" in c1.get("reason", ""), f"got {c1.get('reason')!r}")
    check("「你好，我要分析登录需求」兜底 → analyze（不误伤）",
          classify("你好，我要分析登录需求")["intent"] == "analyze")
    check("「全流程…生成报告」兜底 → full", classify("帮我全流程跑一遍生成报告")["intent"] == "full")
    a1 = qa_answer("你好")
    # DSH 在线时返回模型真实回答；离线时回退到 _OFFLINE_REPLY。两种环境都合法，
    # 关键不变式：绝不静默空答（至少给一句话），且离线时显式声明未调用 AI。
    check("问答回答非空（在线=模型答 / 离线=能力引导）", bool(a1 and a1.strip()), f"got {a1[:60]!r}")
    # 离线分支确定性验证：打桩让 run_turn 返回 error，qa_answer 必须落到 _OFFLINE_REPLY
    import app.services.router as _rt
    _orig_qa = _rt.dsh_manager.run_turn
    _rt.dsh_manager.run_turn = lambda p, session_id=None, on_event=None: {"status": "error"}
    try:
        a_offline = _rt.qa_answer("你好")
    finally:
        _rt.dsh_manager.run_turn = _orig_qa
    check("离线兜底明说未调用 AI", ("未调用 AI" in a_offline) or ("未就绪" in a_offline),
          f"got {a_offline[:60]!r}")
    # 注册表：规则长在 prompt/skill 里
    ic = reg.get_agent("intent-classifier")
    check("intent-classifier prompt 含问候规则", "问候" in ic.system_prompt)
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

    print(f"\n结果：{PASS} PASS / {FAIL} FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
