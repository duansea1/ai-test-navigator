# -*- coding: utf-8 -*-
"""一次性脚本：把 plansea CHANGELOG 明细按功能域归档（中文文件名）。

输入：plansea/_aug_source.md（8月24条）+ plansea/_sep_source.md（9月6条）
输出：
  plansea/changelog/<功能域>.md  — 该域内条目倒序拼接（保留 ## 标题）
  plansea/CHANGELOG.md          — 瘦索引表（每条一行 → 域文件#锚点）

功能域划分（跨域里程碑按主功能归入）：
  DSH运行时与模型.md       Runtime 生命周期/模型切换/网关兼容/会话隔离/collision
  路由与会话.md            意图分类/问答/启发式兜底/多轮会话/会话删除
  Agent流水线与校验.md      8-Agent 流水线/输出强校验/子代理/上下文传递/输入保真
  前端交互与体验.md        UI 重构/流式/弹框/命令面板/空状态
  基础设施与起步.md        Phase1/M0/M1/启动/DB/接口URL/计划校准
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANSEA = ROOT / "plansea"
OUTDIR = PLANSEA / "changelog"

# 按里程碑号/标题关键词归类。key = 域文件名（不含扩展名）。
# 顺序即索引表中域的展示顺序。
DOMAINS: list[tuple[str, list[str]]] = [
    ("DSH运行时与模型", [
        "M3.9", "M3.8", "M3.7.1", "M3.7 ", "M3.6", "DSH Runtime 满血", "Runtime 前置拦截拆除",
    ]),
    ("路由与会话", [
        "路由铁律", "问候语路由修复", "会话删除 + 路由 Agent 会话隔离", "GPT 二次评审",
        "架构定调：智能长在 Agent",
    ]),
    ("Agent流水线与校验", [
        "M3.4.1", "M3.5", "M3.2a", "M3.2b", "M2.3", "M2 多 Agent", "M2.1",
    ]),
    ("前端交互与体验", [
        "M3.0", "M3.1", "M2.2", "问答流式输出", "M3.3", "M3.4 验证补跑",
    ]),
    ("基础设施与起步", [
        "计划校准", "外部评审对照", "M1 ", "M0 ", "接口 URL 精确分析", "多模态需求输入", "一键启动", "本地数据库约定", "Phase 1 MVP",
    ]),
]

# 标题 → 文件 slug 的锚点（GitHub 风格小写连字符，保留 CJK）
def slugify(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^\w\s一-鿿-]", "", t)
    t = re.sub(r"\s+", "-", t.strip())
    return t


def state_of(body: str) -> str:
    m = re.search(r"^状态：\s*\*{0,2}([^*（\n]+)", body, re.MULTILINE)
    if m:
        s = m.group(1).strip()
        if "完成" in s:
            return "✅"
        if "代码完成" in s or "代码落盘" in s:
            return "🟡"
        if "已记录" in s or "待" in s:
            return "📝"
        return s[:6]
    return "—"


def domain_of(title: str) -> str:
    """标题 → 域文件名（不含扩展名）。未匹配归入「其他」。"""
    for domain, keys in DOMAINS:
        for k in keys:
            # 精确匹配里程碑号（避免 M3.4 匹配到 M3.4.1）：用「前缀+空格/中文」
            if k.endswith(" "):
                if k in title or k.strip() + "（" in title:
                    return domain
            elif k in title:
                return domain
    return "其他"


def parse_entries(text: str) -> list[tuple[str, str]]:
    """返回 [(title, body), ...]，body 含原 ## 标题行到下个 ## 之前。"""
    matches = list(re.finditer(r"^## .+$", text, re.MULTILINE))
    entries = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(0)[3:].strip()
        body = text[start:end].rstrip() + "\n"
        entries.append((title, body))
    return entries


def main() -> int:
    aug = (PLANSEA / "_aug_source.md").read_text(encoding="utf-8")
    sep = (PLANSEA / "_sep_source.md").read_text(encoding="utf-8")
    entries = parse_entries(aug) + parse_entries(sep)
    # 按日期倒序（标题含日期 YYYY-MM-DD）
    entries.sort(key=lambda e: e[0], reverse=True)
    print(f"解析到 {len(entries)} 个条目")

    # 按域分组（保持倒序）
    by_domain: dict[str, list[tuple[str, str]]] = {}
    for title, body in entries:
        d = domain_of(title)
        by_domain.setdefault(d, []).append((title, body))

    OUTDIR.mkdir(parents=True, exist_ok=True)
    # 顺序按 DOMAINS 定义，未匹配的域放最后
    domain_order = [d for d, _ in DOMAINS] + (["其他"] if "其他" in by_domain else [])

    lines = [
        "# AI Test Navigator 迭代记录\n\n",
        "> 本文件是**索引**。每条迭代一行，明细见 `changelog/<功能域>.md`。\n",
        "> 里程碑状态总表见 `PLAN.md` §1；能力基线见 `FDE_CAPABILITY_MAP.md`。\n",
        "> 新条目：追加到对应功能域文件顶部，并在本表顶部加一行。\n\n",
        "| 日期 | 功能域 | 状态 | 简述 | 明细 |\n",
        "|---|---|---|---|---|\n",
    ]
    for d in domain_order:
        items = by_domain.get(d, [])
        if not items:
            continue
        fname = f"{d}.md"
        file_text = f"# {d}\n\n"
        for title, body in items:
            file_text += body.rstrip() + "\n\n"
            state = state_of(body[:200])
            date_m = re.match(r"(\d{4}-\d{2}-\d{2})", title)
            date = date_m.group(1) if date_m else "—"
            # 简述：去掉 "YYYY-MM-DD — " 日期前缀，只保留里程碑部分
            desc = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[—–-]\s*", "", title)
            if len(desc) > 60:
                desc = desc[:58] + "…"
            anchor = slugify(title)
            lines.append(f"| {date} | {d} | {state} | {desc} | [`{d}`](changelog/{fname}#{anchor}) |\n")
        (OUTDIR / fname).write_text(file_text, encoding="utf-8")
        print(f"  → {fname}（{len(items)} 条）")

    (PLANSEA / "CHANGELOG.md").write_text("".join(lines), encoding="utf-8")
    print(f"\n索引：{PLANSEA / 'CHANGELOG.md'}（{len(lines)-7} 条）")
    print(f"明细目录：{OUTDIR}（{len(by_domain)} 个功能域文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
