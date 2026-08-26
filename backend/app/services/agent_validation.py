"""Agent 输出强校验层（M2.3）：8-Agent 流水线各阶段输出统一过闸。

背景：此前各阶段仅做 JSON 容错提取（raw_decode）+ 字段映射入库，模型输出
"有 JSON 就收"。本层补齐「不合法结论拒绝入库」的最后一公里：

  1. REQ-xxx 强制：需求 ID 非法时自动规范化（REQ-001 顺序重排），下游阶段
     引用未知名时按位置/文本就近归并，仍无法归并的丢弃并计数。
  2. 枚举收敛：priority / kind / verdict / risk / status 非法值 → 默认值（可疑度+1）。
  3. 数值钳制：confidence ∈ [0,1]；line 为正整数。
  4. 证据完整性：fail 结论必须有 evidence_refs，否则降级 needs_review（核心原则「fail 必须有可复验证据」）。
  5. 每阶段产出 ValidationReport（valid/repaired/dropped 明细），编排层把它带进
     Agent 卡片结论与活动流，人工可见"修了什么、丢了什么"。

设计约束：全部纯函数 + 容错（单条脏数据不炸整个阶段）；不引入 Pydantic 运行时
强校验的硬失败语义（fail-fast 会把「可修复的格式漂移」变成「整阶段降级」，与
单阶段降级策略冲突——先修复、修不动才丢，是更稳的中间态）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ─── 合法枚举（与 models/schemas.py 对齐）─────────────────────────────────────

PRIORITIES = {"P0", "P1", "P2", "P3"}
CASE_KINDS = {"functional", "negative", "boundary", "idempotency", "security"}
VERDICTS = {"pass", "fail", "blocked", "needs_review"}
RISKS = {"high", "medium", "low"}
IMPL_STATUS = {"implemented", "partially_implemented", "not_found", "uncertain"}

_REQ_ID_RE = re.compile(r"^(?:REQ-)?(\d+)$")
_REQ_ID_EMEDDED_RE = re.compile(r"REQ-(\d+)")

# 模型漂移别名（中文/大小写/近义 → 规范枚举）。deepseek-v4-flash 实测会输出
# 中文枚举（如『边界』『高』），一律打回默认值会丢语义，先映射再兜底。
_KIND_ALIASES = {
    "functional": "functional", "功能": "functional", "正常": "functional", "正向": "functional",
    "negative": "negative", "异常": "negative", "反向": "negative", "失败": "negative",
    "boundary": "boundary", "边界": "boundary",
    "idempotency": "idempotency", "幂等": "idempotency",
    "security": "security", "权限": "security", "安全": "security",
}
_RISK_ALIASES = {
    "high": "high", "高": "high", "严重": "high", "高风险": "high",
    "medium": "medium", "中": "medium", "中风险": "medium", "一般": "medium",
    "low": "low", "低": "low", "低风险": "low",
}
_VERDICT_ALIASES = {
    "pass": "pass", "通过": "pass",
    "fail": "fail", "失败": "fail", "不通过": "fail",
    "blocked": "blocked", "阻塞": "blocked",
    "needs_review": "needs_review", "待复核": "needs_review", "需复核": "needs_review",
}
_STATUS_ALIASES = {
    "implemented": "implemented", "已实现": "implemented", "完全实现": "implemented",
    "partially_implemented": "partially_implemented", "部分实现": "partially_implemented",
    "not_found": "not_found", "未找到": "not_found", "未实现": "not_found",
    "uncertain": "uncertain", "不确定": "uncertain",
}


def _alias(v: Any, table: dict[str, str], default: str) -> str:
    """别名映射：命中表 → 规范值；未命中 → default。"""
    key = _s(v).strip().lower()
    return table.get(key, default)


@dataclass
class ValidationReport:
    """单阶段校验结果：进多少 / 修多少 / 丢多少 / 为什么。"""
    total: int = 0
    valid: int = 0          # 原样通过
    repaired: int = 0       # 修复后通过
    dropped: int = 0        # 丢弃（不可救）
    repairs: list[str] = field(default_factory=list)   # 修复说明（进活动流）
    drops: list[str] = field(default_factory=list)     # 丢弃说明（进活动流）

    def note_repair(self, why: str) -> None:
        self.repaired += 1
        if len(self.repairs) < 8:
            self.repairs.append(why)

    def note_drop(self, why: str) -> None:
        self.dropped += 1
        if len(self.drops) < 8:
            self.drops.append(why)

    def summary(self) -> str:
        """Agent 卡片结论用的紧凑统计。"""
        parts = [f"{self.valid} 条通过"]
        if self.repaired:
            parts.append(f"{self.repaired} 条修复")
        if self.dropped:
            parts.append(f"{self.dropped} 条丢弃")
        return "，".join(parts)


# ─── 通用工具 ─────────────────────────────────────────────────────────────────

def _s(v: Any, default: str = "") -> str:
    return v if isinstance(v, str) else default


def _norm_req_id(raw: Any, index: int) -> str:
    """需求 ID 规范化：REQ-3 / 3 / req3 → REQ-003；无数字 → 按序号重排。"""
    raw = _s(raw).strip()
    m = _REQ_ID_RE.match(raw)
    if m:
        return f"REQ-{int(m.group(1)):03d}"
    m = _REQ_ID_EMEDDED_RE.search(raw)
    if m:
        return f"REQ-{int(m.group(1)):03d}"
    return f"REQ-{index:03d}"


def _clamp01(v: Any) -> float | None:
    """置信度钳制 [0,1]；非法 → None。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, f))


def _norm_int(v: Any) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _str_list(v: Any, limit: int = 50) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()][:limit]


# ─── 各阶段校验器 ─────────────────────────────────────────────────────────────

def validate_requirements(items: list[Any], report: ValidationReport) -> list[dict[str, Any]]:
    """requirement-analyst 输出：REQ-xxx 强制 + 优先级收敛 + 去空。"""
    out: list[dict[str, Any]] = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            report.note_drop(f"第 {i} 条非对象，丢弃")
            continue
        title = _s(it.get("title")).strip()
        if not title:
            report.note_drop(f"第 {i} 条无标题，丢弃")
            continue
        rid = _norm_req_id(it.get("id"), i)
        if _s(it.get("id")).strip() not in ("", rid):
            report.note_repair(f"需求 ID 规范化为 {rid}")
        priority = _s(it.get("priority"), "P1").upper()
        if priority not in PRIORITIES:
            priority = _s(it.get("priority")).strip() in ("紧急", "最高", "critical", "high") and "P0" or "P1"
            report.note_repair(f"{rid} 优先级非法 → {priority}")
        out.append({
            "id": rid,
            "title": title[:500],
            "description": _s(it.get("description")),
            "priority": priority,
            "acceptance_criteria": _str_list(it.get("acceptance_criteria")),
        })
        report.total += 1
        report.valid += 1
    return out


def _remap_refs(refs: list[str], valid_ids: list[str], items_meta: list[dict],
                report: ValidationReport, stage: str) -> list[str]:
    """requirement_id 引用归并：精确 → REQ-n 数字 → 就近（按标题文本）→ 丢弃。"""
    out: list[str] = []
    for ref in refs:
        if ref in valid_ids:
            out.append(ref)
            continue
        rid = _norm_req_id(ref, 0)
        if rid != "REQ-000" and rid in valid_ids:
            out.append(rid)
            report.note_repair(f"{stage} 引用 {ref!r} → {rid}")
            continue
        # 就近归并：引用文本与需求标题有包含关系（模型偶尔输出标题当 ID）
        for meta in items_meta:
            if ref and (ref in meta["title"] or meta["title"] in ref):
                out.append(meta["id"])
                report.note_repair(f"{stage} 引用 {ref!r} 归并到 {meta['id']}（标题匹配）")
                break
        else:
            report.note_drop(f"{stage} 引用 {ref!r} 无对应需求，丢弃")
    return list(dict.fromkeys(out))  # 去重保序


def validate_project_scout(projects: list[Any], report: ValidationReport) -> list[dict[str, Any]]:
    """project-scout 输出：relevant 布尔化。"""
    out: list[dict[str, Any]] = []
    for i, p in enumerate(projects, 1):
        if not isinstance(p, dict):
            report.note_drop(f"第 {i} 项非对象，丢弃")
            continue
        name = _s(p.get("name")).strip()
        if not name:
            report.note_drop(f"第 {i} 项无项目名，丢弃")
            continue
        relevant = p.get("relevant")
        if not isinstance(relevant, bool):
            report.note_repair(f"{name} relevant 非布尔 → truthy 判定")
        out.append({"name": name, "relevant": bool(relevant), "reason": _s(p.get("reason"))[:300]})
        report.total += 1
        report.valid += 1
    return out


def validate_evidence(evidence: list[Any], report: ValidationReport,
                      valid_req_ids: list[str] | None = None,
                      items_meta: list[dict] | None = None) -> list[dict[str, Any]]:
    """code-locator 输出：必须有 path；confidence 钳制；line 正整数；req_ref 归并。

    valid_req_ids/items_meta 提供时做 requirement_id 归并（同 _remap_refs），
    未提供或归并失败时 req_ref 留空（证据仍有效，只是不挂需求）。"""
    out: list[dict[str, Any]] = []
    for i, ev in enumerate(evidence, 1):
        if not isinstance(ev, dict):
            report.note_drop(f"证据 {i} 非对象，丢弃")
            continue
        path = _s(ev.get("path")).strip()
        if not path:
            report.note_drop(f"证据 {i} 无路径，丢弃")
            continue
        conf = _clamp01(ev.get("confidence"))
        if conf is None and ev.get("confidence") not in (None, ""):
            report.note_repair(f"证据 {i} 置信度非法 → 置空")
        req_ref = ""
        raw_ref = _s(ev.get("requirement_id")).strip()
        if raw_ref and valid_req_ids and items_meta:
            mapped = _remap_refs([raw_ref], valid_req_ids, items_meta, report, "code-locator")
            req_ref = mapped[0] if mapped else ""
            if not req_ref:
                # 挂错需求不丢证据：路径是实查成果，清空关联降级为「未挂需求」
                report.note_repair(f"证据 {i} requirement_id {raw_ref!r} 无法归并 → 关联清空")
        elif raw_ref:
            req_ref = _norm_req_id(raw_ref, 0)
            if req_ref == "REQ-000":
                req_ref = ""
        out.append({
            "project": _s(ev.get("project")) or "未知项目",
            "path": path[:1000],
            "line": _norm_int(ev.get("line")),
            "symbol": _s(ev.get("symbol"))[:250],
            "snippet": _s(ev.get("snippet"))[:4000],
            "confidence": conf,
            "requirement_id": req_ref,
        })
        report.total += 1
        report.valid += 1
    return out


def _norm_steps(v: Any, limit: int = 30) -> list[dict[str, str]]:
    """链路步骤规范化：兼容对象 {project,component,call} 与纯字符串两种输出。
    （deepseek-v4-flash 实测两种都出；旧实现 _str_list 把对象转成 "{'project': ...}"
    字符串，下游 s.get() 直接崩——先统一成对象再入库。）"""
    out: list[dict[str, str]] = []
    if not isinstance(v, list):
        return out
    for s in v[:limit]:
        if isinstance(s, dict):
            out.append({"project": _s(s.get("project"))[:120],
                        "component": _s(s.get("component"))[:250],
                        "call": _s(s.get("call"))[:500]})
        elif str(s).strip():  # 字符串步骤 → call 一列（无法拆分时保语义不丢）
            out.append({"project": "", "component": "", "call": str(s).strip()[:500]})
    return out


def validate_chains(chains: list[Any], report: ValidationReport) -> list[dict[str, Any]]:
    """call-chain 输出：steps 列表化（对象/字符串双兼容）；risk 枚举收敛。"""
    out: list[dict[str, Any]] = []
    for i, ch in enumerate(chains, 1):
        if not isinstance(ch, dict):
            report.note_drop(f"链路 {i} 非对象，丢弃")
            continue
        name = _s(ch.get("name")).strip() or f"链路-{i}"
        risk = _alias(ch.get("risk"), _RISK_ALIASES, "medium")
        if risk == "medium" and _s(ch.get("risk")).strip().lower() not in ("", "medium"):
            report.note_repair(f"链路「{name}」风险 {_s(ch.get('risk'))!r} 非法 → medium")
        steps = _norm_steps(ch.get("steps"))
        if not steps:
            report.note_drop(f"链路「{name}」无步骤，丢弃")
            continue
        out.append({"name": name[:120], "risk": risk, "steps": steps})
        report.total += 1
        report.valid += 1
    return out


def validate_assessments(assessments: list[Any], report: ValidationReport,
                         valid_req_ids: list[str], items_meta: list[dict],
                         stage: str = "impl-reviewer") -> list[dict[str, Any]]:
    """impl-reviewer / quality-judge 输出校验。

    impl-reviewer 契约：requirement_id/status/verdict/confidence/evidence_refs/gaps
      —— 引用归并 + 枚举收敛 + fail 必须有证据（无证据 fail → needs_review）。
    quality-judge 契约：requirement_id/risk/rationale/recommendation（无 verdict）。
    """
    out: list[dict[str, Any]] = []
    for i, a in enumerate(assessments, 1):
        if not isinstance(a, dict):
            report.note_drop(f"{stage} 第 {i} 条非对象，丢弃")
            continue
        rid = a.get("requirement_id")
        if rid not in valid_req_ids:
            mapped = _remap_refs([_s(rid)], valid_req_ids, items_meta, report, stage)
            rid = mapped[0] if mapped else None
        if rid is None:
            report.note_drop(f"{stage} 第 {i} 条 requirement_id 无法归并，丢弃")
            continue
        entry: dict[str, Any] = {"requirement_id": rid}
        if stage == "impl-reviewer":
            refs = _remap_refs(_str_list(a.get("evidence_refs")), valid_req_ids, items_meta, report, stage)
            verdict = _alias(a.get("verdict"), _VERDICT_ALIASES, "")
            if verdict not in VERDICTS:
                report.note_repair(f"{stage} verdict {_s(a.get('verdict'))!r} 非法 → needs_review")
                verdict = "needs_review"
            if verdict == "fail" and not refs:
                report.note_repair(f"{stage} fail 结论无证据引用 → 降级 needs_review")
                verdict = "needs_review"
            status = _alias(a.get("status"), _STATUS_ALIASES, "")
            if status not in IMPL_STATUS:
                report.note_repair(f"{stage} status {_s(a.get('status'))!r} 非法 → uncertain")
                status = "uncertain"
            entry.update({"verdict": verdict, "status": status,
                          "confidence": _clamp01(a.get("confidence")),
                          "evidence_refs": refs, "gaps": _str_list(a.get("gaps"))})
        else:  # quality-judge
            risk = _alias(a.get("risk"), _RISK_ALIASES, "")
            if risk and risk not in RISKS:
                report.note_repair(f"{stage} risk {_s(a.get('risk'))!r} 非法 → 置空")
                risk = ""
            entry.update({"risk": risk,
                          "rationale": _s(a.get("rationale"))[:1000],
                          "recommendation": _s(a.get("recommendation"))[:1000]})
        out.append(entry)
        report.total += 1
        report.valid += 1
    return out


def validate_test_cases(cases: list[Any], report: ValidationReport,
                        valid_req_ids: list[str], items_meta: list[dict]) -> list[dict[str, Any]]:
    """test-designer 输出：引用归并 + 五类枚举收敛 + steps/expected 必填。"""
    out: list[dict[str, Any]] = []
    for i, c in enumerate(cases, 1):
        if not isinstance(c, dict):
            report.note_drop(f"用例 {i} 非对象，丢弃")
            continue
        title = _s(c.get("title")).strip()
        expected = _s(c.get("expected")).strip()
        if not title or not expected:
            report.note_drop(f"用例 {i} 缺标题或预期结果，丢弃")
            continue
        kind = _alias(c.get("kind"), _KIND_ALIASES, "")
        if kind not in CASE_KINDS:
            report.note_repair(f"用例「{title[:30]}」类型 {_s(c.get('kind'))!r} 非法 → functional")
            kind = "functional"
        rid = c.get("requirement_id")
        if rid not in valid_req_ids:
            mapped = _remap_refs([_s(rid)], valid_req_ids, items_meta, report, "test-designer")
            rid = mapped[0] if mapped else None
        if rid is None:
            report.note_drop(f"用例「{title[:30]}」requirement_id 无法归并，丢弃")
            continue
        out.append({
            "requirement_id": rid,
            "title": title[:500],
            "kind": kind,
            "preconditions": _str_list(c.get("preconditions")),
            "steps": _str_list(c.get("steps")),
            "expected": expected[:2000],
        })
        report.total += 1
        report.valid += 1
    return out


def validate_views(views: Any, report: ValidationReport) -> dict[str, str]:
    """report-writer 输出：三视角必须是字符串且非空。"""
    if not isinstance(views, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("dev", "qa", "product"):
        v = views.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()[:4000]
        elif v is not None:
            report.note_repair(f"{key} 视角非字符串 → 丢弃")
    return out


# ─── 编排层入口 ───────────────────────────────────────────────────────────────

def items_meta_of(items: list[dict[str, Any]]) -> list[dict]:
    """需求条目元信息（供就近归并用）。"""
    return [{"id": it["id"], "title": it.get("title", "")} for it in items]


def validate_stage(agent_id: str, data: Any, items: list[dict[str, Any]] | None = None
                   ) -> tuple[Any, ValidationReport]:
    """按 Agent ID 分发校验。返回 (规范化数据或 None, 校验报告)。

    items 为当前任务已确认的需求条目（阶段 1 之后各阶段引用归并的基准）。
    """
    report = ValidationReport()
    if data is None:
        return None, report
    if agent_id == "requirement-analyst":
        if not isinstance(data, list):
            return None, report
        return validate_requirements(data, report) or None, report
    if agent_id == "project-scout":
        if not isinstance(data, list):
            return None, report
        return validate_project_scout(data, report) or None, report
    if agent_id == "code-locator":
        if not isinstance(data, list):
            return None, report
        if items:
            ids = [it["id"] for it in items]
            return validate_evidence(data, report, ids, items_meta_of(items)) or None, report
        return validate_evidence(data, report) or None, report
    if agent_id == "call-chain":
        if not isinstance(data, list):
            return None, report
        return validate_chains(data, report) or None, report
    if agent_id == "impl-reviewer":
        if not isinstance(data, list) or not items:
            return None, report
        ids = [it["id"] for it in items]
        return validate_assessments(data, report, ids, items_meta_of(items), "impl-reviewer") or None, report
    if agent_id == "test-designer":
        if not isinstance(data, list) or not items:
            return None, report
        ids = [it["id"] for it in items]
        return validate_test_cases(data, report, ids, items_meta_of(items)) or None, report
    if agent_id == "quality-judge":
        if not isinstance(data, list) or not items:
            return None, report
        ids = [it["id"] for it in items]
        return validate_assessments(data, report, ids, items_meta_of(items), "quality-judge") or None, report
    if agent_id == "report-writer":
        # 兼容两种输出：包裹 {"views":{dev,qa,product}} 与裸 {dev,qa,product}。
        # data.get("views") 在裸格式下为 None，此时 data 本身就是 views dict。
        if isinstance(data, dict):
            inner = data.get("views")
            views = inner if isinstance(inner, dict) else data
        else:
            views = data
        return validate_views(views, report) or None, report
    # 未注册校验器的 Agent（路由类）：原样透传
    return data, report
