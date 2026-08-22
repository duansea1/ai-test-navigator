from __future__ import annotations

import html
import json
from pathlib import Path

from app.models.schemas import AnalysisReport


def write_reports(report: AnalysisReport, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = report.report_id
    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    html_path = output_dir / f"{stem}.html"
    payload = report.model_dump(mode="json")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "html": str(html_path)}


def render_markdown(report: AnalysisReport) -> str:
    s = report.summary
    lines = [f"# AI Test Navigator 报告：{report.report_id}", "", f"- 需求来源：`{report.requirement_source}`", f"- 分支：`{report.branch}`", f"- 项目：{', '.join(report.projects)}", "", "## 汇总", "", f"需求 {s['requirements']} · 证据 {s['evidence']} · 影响范围 {s['impacts']} · 测试用例 {s['test_cases']} · 待评审 {s['needs_review']}", "", "## 需求实现矩阵", "", "| ID | 需求 | 实现状态 | 结论 | 置信度 |", "|---|---|---|---|---|"]
    for req in report.requirements:
        a = next((x for x in report.assessments if x.requirement_id == req.id), None)
        lines.append(f"| {req.id} | {req.title} | {a.status.value if a else '-'} | {a.verdict.value if a else '-'} | {a.confidence:.0%} |")
    lines += ["", "## 影响范围", "", "| 需求 | 区域 | 风险 | 受影响项 |", "|---|---|---|---|"]
    for impact in report.impacts:
        lines.append(f"| {impact.requirement_id} | {impact.area} | {impact.risk_level.value} | {'; '.join(impact.affected_items[:3])} |")
    lines += ["", "## 测试用例", "", "| ID | 类型 | 标题 | 预期 |", "|---|---|---|---|"]
    for case in report.test_cases:
        lines.append(f"| {case.id} | {case.kind} | {case.title} | {case.expected} |")
    lines += ["", "## 代码证据", ""]
    for ev in report.evidence:
        lines.append(f"- **{ev.id}** `{ev.project}` `{ev.path}:{ev.line}`：{ev.evidence}")
    lines += ["", "## 说明", ""] + [f"- {note}" for note in report.notes]
    return "\n".join(lines) + "\n"


_STATUS_LABELS = {
    "implemented": ("已实现", "badge ok"),
    "partially_implemented": ("部分实现", "badge warn"),
    "not_found": ("未找到", "badge bad"),
    "uncertain": ("待确认", "badge neutral"),
}

_VERDICT_LABELS = {
    "pass": ("通过", "badge ok"),
    "fail": ("失败", "badge bad"),
    "blocked": ("阻塞", "badge warn"),
    "needs_review": ("待评审", "badge review"),
}

_RISK_LABELS = {
    "high": ("高", "badge bad"),
    "medium": ("中", "badge warn"),
    "low": ("低", "badge ok"),
}


def _badge(value: str, labels: dict[str, tuple[str, str]]) -> str:
    text, cls = labels.get(value, (value, "badge neutral"))
    return f"<span class='{cls}'>{html.escape(text)}</span>"


def _confidence_bar(confidence: float) -> str:
    pct = round(confidence * 100)
    tone = "good" if pct >= 75 else ("mid" if pct >= 50 else "low")
    return (
        f"<div class='meter'><div class='fill {tone}' style='width:{pct}%'></div>"
        f"<span>{pct}%</span></div>"
    )


def _render_html(report: AnalysisReport) -> str:
    s = report.summary
    assessment_by_req = {a.requirement_id: a for a in report.assessments}

    cards = "".join(
        f"<div class='stat'><b>{value}</b><span>{label}</span></div>"
        for label, value in (
            ("需求项", s["requirements"]),
            ("代码证据", s["evidence"]),
            ("影响范围", s["impacts"]),
            ("测试用例", s["test_cases"]),
            ("通过", s["pass"]),
            ("待评审", s["needs_review"]),
        )
    )

    rows = []
    for req in report.requirements:
        a = assessment_by_req.get(req.id)
        status = _badge(a.status.value, _STATUS_LABELS) if a else "<span class='badge neutral'>-</span>"
        verdict = _badge(a.verdict.value, _VERDICT_LABELS) if a else "<span class='badge neutral'>-</span>"
        confidence = _confidence_bar(a.confidence) if a else "-"
        issues = "".join(f"<li>{html.escape(i)}</li>" for i in a.issues) if a else ""
        gaps = "".join(f"<li>{html.escape(g)}</li>" for g in a.gaps) if a else ""
        rows.append(
            "<tr>"
            f"<td>{html.escape(req.id)}</td>"
            f"<td class='title'>{html.escape(req.title)}"
            + (f"<div class='sub'>{html.escape(req.description[:160])}</div>" if req.description and req.description != req.title else "")
            + "</td>"
            f"<td>{status}</td><td>{verdict}</td><td>{confidence}</td>"
            "</tr>"
            + (
                f"<tr class='detail'><td></td><td colspan='4'>"
                + (f"<div class='detail-block'><b>问题</b><ul>{issues}</ul></div>" if issues else "")
                + (f"<div class='detail-block'><b>缺口</b><ul>{gaps}</ul></div>" if gaps else "")
                + (f"<div class='detail-block'><b>结论</b><p>{html.escape(a.summary)}</p></div>" if a else "")
                + "</td></tr>"
                if (issues or gaps or a)
                else ""
            )
        )
    matrix = "".join(rows)

    impact_rows = []
    for impact in report.impacts:
        risk = _badge(impact.risk_level.value, _RISK_LABELS)
        items = "".join(f"<li><code>{html.escape(i)}</code></li>" for i in impact.affected_items)
        impact_rows.append(
            "<tr>"
            f"<td>{html.escape(impact.requirement_id)}</td>"
            f"<td>{html.escape(impact.area)}</td>"
            f"<td>{risk}</td>"
            f"<td><ul class='tight'>{items}</ul></td>"
            "</tr>"
        )
    impact_table = "".join(impact_rows) or "<tr><td colspan='4'>无影响范围数据</td></tr>"

    case_rows = []
    for case in report.test_cases:
        prio = f"<span class='badge {'bad' if case.priority.value == 'P0' else ('warn' if case.priority.value in ('P1', 'P2') else 'neutral')}'>{case.priority.value}</span>"
        steps = "".join(f"<li>{html.escape(x)}</li>" for x in case.steps)
        case_rows.append(
            "<tr>"
            f"<td>{html.escape(case.id)}</td>"
            f"<td>{html.escape(case.kind)}</td>"
            f"<td>{prio}</td>"
            f"<td class='title'>{html.escape(case.title)}</td>"
            f"<td>{html.escape(case.expected)}</td>"
            "</tr>"
            + (f"<tr class='detail'><td></td><td colspan='4'><b>步骤</b><ul class='tight'>{steps}</ul></td></tr>" if steps else "")
        )
    case_table = "".join(case_rows) or "<tr><td colspan='5'>无测试用例</td></tr>"

    evidence_items = []
    for ev in report.evidence:
        evidence_items.append(
            f"<li><b>{html.escape(ev.id)}</b> · <span class='proj'>{html.escape(ev.project)}</span> · "
            f"<code>{html.escape(ev.path)}{':' + str(ev.line) if ev.line else ''}</code>"
            f"<div>{html.escape(ev.evidence)}"
            + (f" <span class='sub'>（{html.escape(ev.relevance)}）</span>" if ev.relevance else "")
            + "</div></li>"
        )
    evidence_html = "".join(evidence_items) or "<li>无代码证据</li>"

    commits = "".join(f"<li><b>{html.escape(p)}</b>: <code>{html.escape(c)}</code></li>" for p, c in report.commit_info.items())
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in report.notes)
    generated = report.generated_at.strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang='zh-CN'>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>AI Test Navigator 报告 {report.report_id}</title>
<style>
:root{{--ok:#16803c;--ok-bg:#e6f6ec;--bad:#c5221f;--bad-bg:#fdecea;--warn:#9a6700;--warn-bg:#fff3d6;--review:#57606a;--review-bg:#eef1f4;--line:#d8dee7;--ink:#172033;--sub:#5a6577}}
*{{box-sizing:border-box}}
body{{font-family:'Segoe UI',Arial,'Microsoft Yahei',sans-serif;max-width:1360px;margin:0 auto;padding:28px 24px 64px;line-height:1.65;color:var(--ink);background:#fafbfc}}
h1{{font-size:24px;margin:0 0 4px}}
h2{{font-size:17px;margin:36px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--line)}}
.meta{{color:var(--sub);font-size:13px;margin-bottom:18px}}
.meta code{{background:#eef1f4;padding:1px 6px;border-radius:4px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:18px 0 6px}}
.stat{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 16px;text-align:center}}
.stat b{{display:block;font-size:26px}}
.stat span{{color:var(--sub);font-size:12px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13.5px}}
th{{background:#f0f3f8;text-align:left;padding:9px 12px;font-size:12.5px;color:var(--sub);border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:9px 12px;border-bottom:1px solid #edf0f4;vertical-align:top}}
tr:last-child td{{border-bottom:none}}
tr.detail td{{background:#f8fafc;font-size:13px}}
td.title{{font-weight:600;min-width:260px}}
.sub{{color:var(--sub);font-size:12px}}
ul{{margin:4px 0 4px 18px;padding:0}}
ul.tight li{{margin:2px 0}}
code{{font-family:Consolas,monospace;font-size:12.5px;background:#f0f3f8;padding:1px 5px;border-radius:4px;word-break:break-all}}
.badge{{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}}
.badge.ok{{color:var(--ok);background:var(--ok-bg)}}
.badge.bad{{color:var(--bad);background:var(--bad-bg)}}
.badge.warn{{color:var(--warn);background:var(--warn-bg)}}
.badge.review{{color:var(--review);background:var(--review-bg)}}
.badge.neutral{{color:var(--review);background:var(--review-bg)}}
.meter{{display:flex;align-items:center;gap:8px;min-width:110px}}
.meter div{{height:8px;border-radius:999px;background:#e6eaf0;flex:1;overflow:hidden;position:relative}}
.meter .fill{{position:absolute;left:0;top:0;bottom:0;border-radius:999px}}
.fill.good{{background:var(--ok)}}.fill.mid{{background:#d29922}}.fill.low{{background:var(--bad)}}
.meter span{{font-size:12px;color:var(--sub);width:36px;text-align:right}}
details{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:8px 0}}
summary{{cursor:pointer;font-weight:600;color:#183b9b}}
.proj{{color:#183b9b;font-weight:600;font-size:12.5px}}
.detail-block{{margin:4px 0}}
.detail-block b{{font-size:12.5px;color:var(--sub)}}
</style>
<h1>AI Test Navigator 质量分析报告</h1>
<div class='meta'>报告 <code>{report.report_id}</code> · 生成于 {generated} · 分支 <code>{html.escape(report.branch)}</code> · 需求来源 <code>{html.escape(report.requirement_source)}</code></div>
<div class='stats'>{cards}</div>
<h2>需求实现矩阵</h2>
<table>
<tr><th>ID</th><th>需求</th><th>实现状态</th><th>结论</th><th>置信度</th></tr>
{matrix}
</table>
<h2>影响范围</h2>
<table>
<tr><th>需求</th><th>区域</th><th>风险</th><th>受影响项</th></tr>
{impact_table}
</table>
<h2>测试用例</h2>
<table>
<tr><th>ID</th><th>类型</th><th>优先级</th><th>标题</th><th>预期结果</th></tr>
{case_table}
</table>
<h2>代码证据</h2>
<details open><summary>共 {len(report.evidence)} 条证据</summary>
<ul class='tight'>{evidence_html}</ul>
</details>
<h2>提交信息</h2>
<details><summary>项目 commit 快照</summary><ul class='tight'>{commits}</ul></details>
<h2>说明</h2>
<ul>{notes}</ul>
</html>"""


def render_html(report: AnalysisReport) -> str:
    return _render_html(report)
