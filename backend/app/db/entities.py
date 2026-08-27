"""表结构（DDL）与数据访问（repository）。

表清单与 plansea/DATABASE.md 对齐（均含 COMMENT 备注，SQLite 方言自动剥离）：
analysis_tasks / requirements / code_evidence / impact_scopes / test_cases /
test_runs / assessments / reports / agent_sessions / dsh_events / model_configs
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.db import engine

# ─── DDL（两方言各一份，语义一致）────────────────────────────────────────────

_TASKS = """
CREATE TABLE IF NOT EXISTS analysis_tasks (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) NOT NULL UNIQUE COMMENT '任务唯一标识（对外 ID）',
  title VARCHAR(512) NOT NULL COMMENT '任务标题',
  source_text MEDIUMTEXT COMMENT '原始需求/分析输入文本',
  projects VARCHAR(512) NOT NULL DEFAULT '' COMMENT '涉及项目列表（逗号分隔）',
  branch VARCHAR(128) NOT NULL DEFAULT '' COMMENT '分析分支',
  workspace VARCHAR(512) NOT NULL DEFAULT '' COMMENT '工作区路径',
  status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '任务状态：pending/running/completed/failed/cancelled',
  stage VARCHAR(64) NOT NULL DEFAULT '' COMMENT '当前分析阶段',
  progress INT NOT NULL DEFAULT 0 COMMENT '进度百分比 0-100',
  message TEXT COMMENT '进度/状态消息',
  report_id VARCHAR(64) COMMENT '关联报告 ID',
  error TEXT COMMENT '错误信息',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  updated_at DATETIME NOT NULL COMMENT '更新时间',
  INDEX idx_tasks_status (status),
  INDEX idx_tasks_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分析任务主表'
"""

_REQUIREMENTS = """
CREATE TABLE IF NOT EXISTS requirements (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  req_id VARCHAR(64) NOT NULL COMMENT '需求唯一标识',
  title VARCHAR(512) NOT NULL COMMENT '需求标题',
  description TEXT COMMENT '需求描述',
  priority VARCHAR(16) NOT NULL DEFAULT 'P1' COMMENT '优先级：P0/P1/P2/P3',
  acceptance_criteria TEXT COMMENT '验收标准',
  status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '需求状态：pending/analyzed/verified/covered',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_req_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='需求条目表'
"""

_CODE_EVIDENCE = """
CREATE TABLE IF NOT EXISTS code_evidence (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  project VARCHAR(128) COMMENT '所属项目',
  path VARCHAR(1024) COMMENT '代码文件路径',
  line_no INT COMMENT '行号',
  symbol VARCHAR(256) COMMENT '符号名（函数/类/变量）',
  summary TEXT COMMENT '代码摘要',
  relevance VARCHAR(32) COMMENT '相关度：high/medium/low',
  req_ref VARCHAR(64) COMMENT '关联需求 ID（REQ-xxx）',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_ev_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='代码证据表'
"""

_IMPACT = """
CREATE TABLE IF NOT EXISTS impact_scopes (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  project VARCHAR(128) COMMENT '所属项目',
  area VARCHAR(128) COMMENT '影响范围（模块/服务）',
  risk_level VARCHAR(16) COMMENT '风险等级：high/medium/low',
  affected_items TEXT COMMENT '受影响项清单',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_imp_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='影响范围表'
"""

_TEST_CASES = """
CREATE TABLE IF NOT EXISTS test_cases (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  req_ref VARCHAR(64) COMMENT '关联需求 ID',
  case_type VARCHAR(32) COMMENT '用例类型：function/integration/e2e',
  title VARCHAR(512) COMMENT '用例标题',
  steps TEXT COMMENT '测试步骤',
  expected TEXT COMMENT '预期结果',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_tc_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='测试用例表'
"""

_TEST_RUNS = """
CREATE TABLE IF NOT EXISTS test_runs (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) COMMENT '关联任务 ID',
  command VARCHAR(1024) COMMENT '执行命令',
  exit_code INT COMMENT '退出码',
  duration_ms INT COMMENT '耗时（毫秒）',
  status VARCHAR(32) COMMENT '运行状态：running/passed/failed',
  log_excerpt TEXT COMMENT '日志摘要',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_tr_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='测试执行记录表'
"""

_ASSESSMENTS = """
CREATE TABLE IF NOT EXISTS assessments (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) NOT NULL COMMENT '关联任务 ID',
  req_ref VARCHAR(64) COMMENT '关联需求 ID',
  verdict VARCHAR(32) COMMENT '评估结论：covered/gap/risk',
  risk VARCHAR(16) COMMENT '风险等级：high/medium/low',
  confidence DECIMAL(4,3) COMMENT '置信度 0-1',
  evidence_refs TEXT COMMENT '证据引用',
  gaps TEXT COMMENT '缺口说明',
  needs_review TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否需人工复核：0/1',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_as_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='需求评估表'
"""

_REPORTS = """
CREATE TABLE IF NOT EXISTS reports (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) COMMENT '关联任务 ID',
  report_id VARCHAR(64) NOT NULL UNIQUE COMMENT '报告唯一标识',
  version INT NOT NULL DEFAULT 1 COMMENT '版本号',
  files TEXT COMMENT '报告文件路径清单',
  summary TEXT COMMENT '报告摘要',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_rp_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分析报告表'
"""

_AGENT_SESSIONS = """
CREATE TABLE IF NOT EXISTS agent_sessions (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) COMMENT '关联任务 ID',
  agent_id VARCHAR(64) COMMENT 'Agent 标识',
  session_id VARCHAR(128) COMMENT 'DSH 会话 ID',
  status VARCHAR(32) COMMENT '会话状态：running/done/error',
  turns INT NOT NULL DEFAULT 0 COMMENT '对话轮次',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_ag_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent 会话表'
"""

_DSH_EVENTS = """
CREATE TABLE IF NOT EXISTS dsh_events (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  task_id VARCHAR(64) COMMENT '关联任务 ID',
  session_id VARCHAR(128) COMMENT 'DSH 会话 ID',
  event_type VARCHAR(64) COMMENT '事件类型（如 token/tool_call/step/error）',
  payload TEXT COMMENT '事件载荷（JSON）',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_de_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='DSH 事件流表'
"""

_MODEL_CONFIGS = """
CREATE TABLE IF NOT EXISTS model_configs (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  provider_key VARCHAR(64) NOT NULL UNIQUE COMMENT '供应商唯一 key（英文）',
  display_name VARCHAR(128) NOT NULL COMMENT '显示名',
  api_key TEXT COMMENT 'API Key（明文，本地存储）',
  base_url VARCHAR(512) COMMENT 'API 地址（Base URL）',
  protocol VARCHAR(32) NOT NULL DEFAULT 'openai-completions' COMMENT 'API 协议：openai-completions/openai-responses/anthropic/gemini',
  model_ids TEXT NOT NULL COMMENT '模型 ID 列表（JSON 数组）',
  is_custom TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否自定义：0/1',
  is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认供应商：0/1',
  enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：0/1',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  updated_at DATETIME NOT NULL COMMENT '更新时间',
  INDEX idx_mc_default (is_default),
  INDEX idx_mc_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模型供应商配置表'
"""

_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS conversations (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  conv_id VARCHAR(64) NOT NULL UNIQUE COMMENT '会话唯一标识（对外 ID）',
  title VARCHAR(512) NOT NULL DEFAULT '新会话' COMMENT '会话标题（首条消息截断）',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  updated_at DATETIME NOT NULL COMMENT '更新时间',
  INDEX idx_conv_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户会话表（多轮对话载体）'
"""

_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  conv_id VARCHAR(64) NOT NULL COMMENT '关联会话 ID',
  role VARCHAR(16) NOT NULL COMMENT '角色：user/assistant',
  content TEXT COMMENT '消息内容',
  intent VARCHAR(16) COMMENT '意图标签（assistant 消息）：qa/analyze/full',
  task_id VARCHAR(64) COMMENT '关联分析任务 ID（analyze/full 消息）',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  INDEX idx_cm_conv (conv_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话消息表'
"""


def _sqlite(ddl: str) -> list[str]:
    """MySQL DDL → SQLite：去引擎/表注释子句、AUTO_INCREMENT→AUTOINCREMENT、索引单独建。"""
    import re as _re

    out = []
    for stmt in [_re.sub(r"\)\s*ENGINE[^\n]*", ")", ddl, flags=_re.IGNORECASE)]:
        s = stmt.strip()
        if not s:
            continue
        # 剥离 MySQL 列级/表级 COMMENT 子句（SQLite 不支持）
        s = _re.sub(r"COMMENT\s+'[^']*'", "", s)
        s = s.replace("id INT AUTO_INCREMENT PRIMARY KEY", "id INTEGER PRIMARY KEY AUTOINCREMENT")
        s = s.replace("AUTO_INCREMENT", "")
        s = s.replace("MEDIUMTEXT", "TEXT")
        s = s.replace("DATETIME", "TEXT")
        s = s.replace("DECIMAL(4,3)", "REAL")
        s = s.replace("TINYINT(1)", "INTEGER")
        s = re_index(s)
        out.append(s)
    return out


def re_index(stmt: str) -> str:
    """去掉内联 INDEX 行（SQLite 索引单独建），并清理残留尾逗号。"""
    lines = [l for l in stmt.splitlines() if "INDEX idx_" not in l]
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith(")"):
            continue
        if lines[i].rstrip().endswith(","):
            lines[i] = lines[i].rstrip()[:-1]
        break
    return "\n".join(lines)


def _build_sqlite_schema() -> list[str]:
    stmts: list[str] = []
    for ddl in (_TASKS, _REQUIREMENTS, _CODE_EVIDENCE, _IMPACT, _TEST_CASES,
                _TEST_RUNS, _ASSESSMENTS, _REPORTS, _AGENT_SESSIONS, _DSH_EVENTS,
                _MODEL_CONFIGS, _CONVERSATIONS, _CHAT_MESSAGES):
        stmts.extend(_sqlite(ddl))
    # SQLite 索引
    for tbl, col in [("analysis_tasks", "status"), ("analysis_tasks", "created_at"),
                     ("requirements", "task_id"), ("code_evidence", "task_id"),
                     ("impact_scopes", "task_id"), ("test_cases", "task_id"),
                     ("test_runs", "task_id"), ("assessments", "task_id"),
                     ("reports", "task_id"), ("agent_sessions", "task_id"),
                     ("dsh_events", "task_id"), ("model_configs", "is_default"),
                     ("model_configs", "enabled"), ("conversations", "updated_at"),
                     ("chat_messages", "conv_id")]:
        stmts.append(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_{col} ON {tbl} ({col})")
    return stmts


SCHEMA_MYSQL = [_TASKS, _REQUIREMENTS, _CODE_EVIDENCE, _IMPACT, _TEST_CASES,
                _TEST_RUNS, _ASSESSMENTS, _REPORTS, _AGENT_SESSIONS, _DSH_EVENTS,
                _MODEL_CONFIGS, _CONVERSATIONS, _CHAT_MESSAGES]
SCHEMA_SQLITE = _build_sqlite_schema()


# ─── repository：analysis_tasks ──────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_task(title: str, source_text: str, projects: str, branch: str, workspace: str) -> str:
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    now = _now()
    engine.insert(
        "INSERT INTO analysis_tasks (task_id, title, source_text, projects, branch, workspace, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        (task_id, title[:500], source_text, projects, branch, workspace, now, now),
    )
    return task_id


def update_task(task_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [_now(), task_id]
    engine.execute(f"UPDATE analysis_tasks SET {sets}, updated_at = ? WHERE task_id = ?", params)


def get_task(task_id: str) -> dict[str, Any] | None:
    row = engine.query_one("SELECT * FROM analysis_tasks WHERE task_id = ?", (task_id,))
    return _task_row(row)


def _task_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    row["report_id"] = row.get("report_id")
    return row


def list_tasks(limit: int = 50, status: str = "") -> list[dict[str, Any]]:
    if status:
        return engine.query(
            "SELECT task_id, title, projects, branch, status, stage, progress, message, report_id, error, created_at, updated_at "
            "FROM analysis_tasks WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit),
        )
    return engine.query(
        "SELECT task_id, title, projects, branch, status, stage, progress, message, report_id, error, created_at, updated_at "
        "FROM analysis_tasks ORDER BY id DESC LIMIT ?",
        (limit,),
    )


# ─── repository：requirements ────────────────────────────────────────────────

def save_requirements(task_id: str, items: list[dict[str, Any]]) -> int:
    """批量写入需求条目（先清旧，任务可重复解析）。"""
    engine.execute("DELETE FROM requirements WHERE task_id = ?", (task_id,))
    for it in items:
        engine.insert(
            "INSERT INTO requirements (task_id, req_id, title, description, priority, acceptance_criteria, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, str(it.get("id", ""))[:60], str(it.get("title", ""))[:500],
             it.get("description", ""), str(it.get("priority", "P1"))[:15],
             engine.dumps(it.get("acceptance_criteria", [])), "pending", _now()),
        )
    return len(items)


def list_requirements(task_id: str) -> list[dict[str, Any]]:
    rows = engine.query("SELECT * FROM requirements WHERE task_id = ? ORDER BY id", (task_id,))
    for r in rows:
        r["acceptance_criteria"] = engine.loads(r.get("acceptance_criteria"), [])
    return rows


# ─── repository：reports / agent_sessions ────────────────────────────────────

def save_report(task_id: str, report_id: str, files: dict[str, str], summary: dict[str, Any]) -> None:
    engine.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
    engine.insert(
        "INSERT INTO reports (task_id, report_id, version, files, summary, created_at) VALUES (?, ?, 1, ?, ?, ?)",
        (task_id, report_id, engine.dumps(files), engine.dumps(summary), _now()),
    )


def save_agent_session(task_id: str, agent_id: str, session_id: str, status: str, turns: int) -> None:
    engine.insert(
        "INSERT INTO agent_sessions (task_id, agent_id, session_id, status, turns, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, agent_id, session_id, status, turns, _now()),
    )


def list_agent_sessions(task_id: str) -> list[dict[str, Any]]:
    return engine.query("SELECT agent_id, session_id, status, turns, created_at FROM agent_sessions WHERE task_id = ? ORDER BY id", (task_id,))


def save_dsh_event(task_id: str, agent_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Agent 生命周期事件入库（聊天时间线持久化，进程重启后可重建粗粒度回放）。"""
    engine.insert(
        "INSERT INTO dsh_events (task_id, session_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, agent_id, event_type, engine.dumps(payload), _now()),
    )


def list_dsh_events(task_id: str) -> list[dict[str, Any]]:
    rows = engine.query("SELECT session_id, event_type, payload, created_at FROM dsh_events WHERE task_id = ? ORDER BY id", (task_id,))
    for r in rows:
        r["payload"] = engine.loads(r.get("payload"), {})
    return rows


def fail_stale_tasks() -> int:
    """服务启动时清理僵尸任务：上次进程退出时未到终态的任务标记中断。"""
    return engine.execute(
        "UPDATE analysis_tasks SET status = 'failed', error = '服务重启，任务中断', "
        "stage = 'interrupted', message = '服务重启，任务中断' WHERE status IN ('pending', 'running')",
    )


# ─── 轻量列迁移：已有表补列（init_schema 后执行，可重复）──────────────────

_MIGRATIONS = [
    ("assessments", "risk", "VARCHAR(16)"),
    ("assessments", "gaps", "TEXT"),
    ("code_evidence", "req_ref", "VARCHAR(64)"),
]


def _migrate_columns() -> None:
    """轻量迁移：直接尝试 ALTER，列已存在时捕获异常忽略（可重复执行）。"""
    for table, column, ddl_type in _MIGRATIONS:
        try:
            engine.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
        except Exception:
            pass  # 列已存在（MySQL 1060 / SQLite duplicate column）


# ─── repository：code_evidence / impact_scopes / test_cases / assessments ───

def save_code_evidence(task_id: str, evidence: list[dict[str, Any]]) -> int:
    """代码证据入库（code-locator 输出，先清旧；req_ref 关联需求条目）。"""
    engine.execute("DELETE FROM code_evidence WHERE task_id = ?", (task_id,))
    for ev in evidence:
        engine.insert(
            "INSERT INTO code_evidence (task_id, project, path, line_no, symbol, summary, relevance, req_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, str(ev.get("project", ""))[:120], str(ev.get("path", ""))[:1000],
             _to_int(ev.get("line")), str(ev.get("symbol", ""))[:250],
             str(ev.get("snippet", ev.get("summary", "")))[:4000],
             str(ev.get("confidence", ""))[:30],
             str(ev.get("requirement_id", ""))[:60], _now()),
        )
    return len(evidence)


def _to_int(v: Any) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def list_code_evidence(task_id: str) -> list[dict[str, Any]]:
    return engine.query("SELECT * FROM code_evidence WHERE task_id = ? ORDER BY id", (task_id,))


def save_impact_scopes(task_id: str, chains: list[dict[str, Any]]) -> int:
    """影响范围入库（call-chain 输出 chains[{name,steps[]}] → 每链一行）。"""
    engine.execute("DELETE FROM impact_scopes WHERE task_id = ?", (task_id,))
    for ch in chains:
        engine.insert(
            "INSERT INTO impact_scopes (task_id, project, area, risk_level, affected_items, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, ", ".join(dict.fromkeys(str(s.get("project", "")) for s in ch.get("steps", []) if s.get("project")))[:120],
             str(ch.get("name", "未命名链路"))[:120], str(ch.get("risk", "medium"))[:15],
             engine.dumps(ch.get("steps", [])), _now()),
        )
    return len(chains)


def list_impact_scopes(task_id: str) -> list[dict[str, Any]]:
    rows = engine.query("SELECT * FROM impact_scopes WHERE task_id = ? ORDER BY id", (task_id,))
    for r in rows:
        r["steps"] = engine.loads(r.get("affected_items"), [])
    return rows


def save_test_cases(task_id: str, cases: list[dict[str, Any]]) -> int:
    """测试用例入库（test-designer 输出，五类用例）。"""
    engine.execute("DELETE FROM test_cases WHERE task_id = ?", (task_id,))
    for c in cases:
        engine.insert(
            "INSERT INTO test_cases (task_id, req_ref, case_type, title, steps, expected, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, str(c.get("requirement_id", ""))[:60], str(c.get("kind", "functional"))[:30],
             str(c.get("title", ""))[:500],
             engine.dumps({"preconditions": c.get("preconditions", []), "steps": c.get("steps", [])}),
             str(c.get("expected", ""))[:2000], _now()),
        )
    return len(cases)


def list_test_cases(task_id: str) -> list[dict[str, Any]]:
    rows = engine.query("SELECT * FROM test_cases WHERE task_id = ? ORDER BY id", (task_id,))
    for r in rows:
        detail = engine.loads(r.get("steps"), {})
        r["preconditions"] = detail.get("preconditions", [])
        r["steps"] = detail.get("steps", [])
    return rows


def save_assessments(task_id: str, assessments: list[dict[str, Any]]) -> int:
    """实现审查结论入库（impl-reviewer + quality-judge 合并写入）。"""
    engine.execute("DELETE FROM assessments WHERE task_id = ?", (task_id,))
    for a in assessments:
        conf = a.get("confidence")
        try:
            conf_val = float(conf) if conf not in (None, "") else None
        except (TypeError, ValueError):
            conf_val = None
        engine.insert(
            "INSERT INTO assessments (task_id, req_ref, verdict, risk, confidence, evidence_refs, gaps, needs_review, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, str(a.get("requirement_id", a.get("req_ref", "")))[:60],
             str(a.get("verdict", ""))[:30], str(a.get("risk", ""))[:15],
             conf_val, engine.dumps(a.get("evidence_refs", [])),
             engine.dumps(a.get("gaps", [])),
             1 if a.get("verdict") in ("needs_review", "blocked") or a.get("needs_review") else 0, _now()),
        )
    return len(assessments)


def list_assessments(task_id: str) -> list[dict[str, Any]]:
    rows = engine.query("SELECT * FROM assessments WHERE task_id = ? ORDER BY id", (task_id,))
    for r in rows:
        r["evidence_refs"] = engine.loads(r.get("evidence_refs"), [])
        r["gaps"] = engine.loads(r.get("gaps"), [])
    return rows


def save_report_views(task_id: str, views: dict[str, Any]) -> None:
    """三视角摘要（report-writer 输出）合并进任务最新报告行。"""
    row = engine.query_one(
        "SELECT report_id FROM reports WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,))
    if row is None:
        return
    engine.execute(
        "UPDATE reports SET summary = ? WHERE report_id = ?",
        (engine.dumps({"views": views}), row["report_id"]),
    )


def list_report_views(task_id: str) -> dict[str, Any]:
    row = engine.query_one(
        "SELECT summary FROM reports WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,))
    if row is None:
        return {}
    data = engine.loads(row.get("summary"), {})
    return data.get("views", {}) if isinstance(data, dict) else {}


# ─── repository：conversations / chat_messages（多轮会话，M3.2a）──────────────

def create_conversation(title: str = "新会话") -> str:
    conv_id = f"conv-{uuid.uuid4().hex[:12]}"
    now = _now()
    engine.insert(
        "INSERT INTO conversations (conv_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (conv_id, title[:500], now, now),
    )
    return conv_id


def touch_conversation(conv_id: str, title: str | None = None) -> None:
    """会话有新消息：刷新 updated_at；首条用户消息定标题。"""
    if title:
        engine.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE conv_id = ?",
            (title[:500], _now(), conv_id),
        )
    else:
        engine.execute(
            "UPDATE conversations SET updated_at = ? WHERE conv_id = ?",
            (_now(), conv_id),
        )


def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    return engine.query(
        "SELECT conv_id, title, created_at, updated_at FROM conversations "
        "ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )


def get_conversation(conv_id: str) -> dict[str, Any] | None:
    return engine.query_one(
        "SELECT conv_id, title, created_at, updated_at FROM conversations WHERE conv_id = ?",
        (conv_id,),
    )


def save_message(conv_id: str, role: str, content: str,
                 intent: str = "", task_id: str = "") -> None:
    """追加一条会话消息（user / assistant）；task_id 关联分析任务块。"""
    engine.insert(
        "INSERT INTO chat_messages (conv_id, role, content, intent, task_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, role, content, intent or None, task_id or None, _now()),
    )


def list_messages(conv_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """会话消息按时间正序（先取最新 limit 条再反转，长会话只带尾部上下文）。"""
    rows = engine.query(
        "SELECT role, content, intent, task_id, created_at FROM chat_messages "
        "WHERE conv_id = ? ORDER BY id DESC LIMIT ?",
        (conv_id, limit),
    )
    rows.reverse()
    return rows


# ─── repository：会话删除（M3.2c，2026-08-27）─────────────────────────────────

# 任务关联的从表（删任务时一并清，避免孤儿数据）。与 analysis_tasks 无外键约束，
# 手动维护清单——新增任务衍生表时记得追加。
_TASK_CHILD_TABLES: tuple[str, ...] = (
    "requirements", "code_evidence", "impact_scopes", "test_cases",
    "assessments", "reports", "agent_sessions", "dsh_events",
)


def delete_task(task_id: str) -> bool:
    """删除单个分析任务及其全部衍生数据（七表级联）。

    会话删除时对会话内每个任务调用本函数；也可独立用于任务删除。
    返回 True 表示 analysis_tasks 有该行被删。"""
    existed = engine.scalar("SELECT 1 FROM analysis_tasks WHERE task_id = ?", (task_id,))
    for tbl in _TASK_CHILD_TABLES:
        engine.execute(f"DELETE FROM {tbl} WHERE task_id = ?", (task_id,))
    engine.execute("DELETE FROM analysis_tasks WHERE task_id = ?", (task_id,))
    return bool(existed)


def delete_conversation(conv_id: str) -> dict[str, Any]:
    """删除一个会话：连带删 chat_messages + 会话内所有任务及其衍生数据。

    级联关系：会话 → chat_messages.task_id 指向的任务 → 任务衍生七表。
    返回 {existed, deleted_tasks}。会话内的任务被全删（避免任务悬空没人能打开）。
    """
    conv = get_conversation(conv_id)
    existed = conv is not None
    # 先收集会话内挂的任务（删 chat_messages 前取，免得丢失引用）
    task_rows = engine.query(
        "SELECT DISTINCT task_id FROM chat_messages "
        "WHERE conv_id = ? AND task_id IS NOT NULL AND task_id != ''",
        (conv_id,),
    )
    deleted_tasks = [r["task_id"] for r in task_rows if r.get("task_id")]
    engine.execute("DELETE FROM chat_messages WHERE conv_id = ?", (conv_id,))
    engine.execute("DELETE FROM conversations WHERE conv_id = ?", (conv_id,))
    # 级联删除会话内每个任务（任务的全套衍生数据跟着走）
    for tid in deleted_tasks:
        delete_task(tid)
    return {"existed": existed, "deleted_tasks": deleted_tasks}


# ─── repository：dashboard 聚合 ──────────────────────────────────────────────

def dashboard_stats() -> dict[str, Any]:
    total = engine.scalar("SELECT COUNT(*) FROM analysis_tasks") or 0
    running = engine.scalar("SELECT COUNT(*) FROM analysis_tasks WHERE status IN ('pending','running')") or 0
    completed = engine.scalar("SELECT COUNT(*) FROM analysis_tasks WHERE status = 'completed'") or 0
    failed = engine.scalar("SELECT COUNT(*) FROM analysis_tasks WHERE status = 'failed'") or 0
    reqs = engine.scalar("SELECT COUNT(*) FROM requirements") or 0
    evidence = engine.scalar("SELECT COUNT(*) FROM code_evidence") or 0
    cases = engine.scalar("SELECT COUNT(*) FROM test_cases") or 0
    review = engine.scalar("SELECT COUNT(*) FROM assessments WHERE needs_review = 1") or 0
    return {"tasks_total": total, "tasks_running": running, "tasks_completed": completed,
            "tasks_failed": failed, "requirements_total": reqs,
            "evidence_total": evidence, "test_cases_total": cases, "needs_review_total": review}


def dashboard_trend(days: int = 14) -> list[dict[str, Any]]:
    """近 N 天每日任务量与需求数。"""
    rows = engine.query(
        "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS tasks FROM analysis_tasks "
        "GROUP BY substr(created_at, 1, 10) ORDER BY day DESC LIMIT ?",
        (days,),
    )
    rows.reverse()
    return rows


# ─── repository：model_configs（模型供应商配置，明文存储，本地用）─────────────

def _mask_key(key: str | None) -> str | None:
    """API Key 脱敏：保留首尾各 4 位，中间打码。空值返回 None。"""
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def list_model_configs() -> list[dict[str, Any]]:
    """列出全部供应商配置（api_key 已脱敏）。"""
    rows = engine.query("SELECT * FROM model_configs ORDER BY is_default DESC, id")
    out = []
    for r in rows:
        r["model_ids"] = engine.loads(r.get("model_ids"), [])
        r["api_key"] = _mask_key(r.get("api_key"))
        out.append(r)
    return out


def get_model_config_full(provider_key: str) -> dict[str, Any] | None:
    """按 key 取完整配置（含明文 api_key），供编辑/连通测试使用。"""
    r = engine.query_one("SELECT * FROM model_configs WHERE provider_key = ?", (provider_key,))
    if r is None:
        return None
    r["model_ids"] = engine.loads(r.get("model_ids"), [])
    return r


def upsert_model_config(provider_key: str, display_name: str, api_key: str | None,
                        base_url: str | None, protocol: str, model_ids: list[str],
                        is_custom: bool, enabled: bool) -> None:
    """新增或更新供应商配置（api_key 为空表示沿用既有值，不覆盖）。"""
    now = _now()
    existing = engine.query_one("SELECT id FROM model_configs WHERE provider_key = ?", (provider_key,))
    if existing:
        sets = ["display_name = ?", "base_url = ?", "protocol = ?",
                "model_ids = ?", "is_custom = ?", "enabled = ?", "updated_at = ?"]
        params: list[Any] = [display_name, base_url, protocol, engine.dumps(model_ids),
                              1 if is_custom else 0, 1 if enabled else 0, now]
        if api_key:  # 仅在提供新 key 时覆盖
            sets.append("api_key = ?")
            params.append(api_key)
        params.append(provider_key)
        engine.execute(f"UPDATE model_configs SET {', '.join(sets)} WHERE provider_key = ?", params)
    else:
        engine.insert(
            "INSERT INTO model_configs (provider_key, display_name, api_key, base_url, protocol, model_ids, is_custom, is_default, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (provider_key, display_name, api_key, base_url, protocol, engine.dumps(model_ids),
             1 if is_custom else 0, 1 if enabled else 0, now, now),
        )


def set_default_model_config(provider_key: str) -> None:
    """将某配置置为默认（清除其它默认标记）。"""
    engine.execute("UPDATE model_configs SET is_default = 0")
    engine.execute("UPDATE model_configs SET is_default = 1 WHERE provider_key = ?", (provider_key,))


def delete_model_config(provider_key: str) -> None:
    engine.execute("DELETE FROM model_configs WHERE provider_key = ?", (provider_key,))


def get_default_model_config() -> dict[str, Any] | None:
    """取默认配置；无默认则取首个启用项。"""
    r = engine.query_one("SELECT * FROM model_configs WHERE is_default = 1", ())
    if r is None:
        r = engine.query_one("SELECT * FROM model_configs WHERE enabled = 1 ORDER BY id", ())
    if r is None:
        return None
    r["model_ids"] = engine.loads(r.get("model_ids"), [])
    return r


def restore_default_model_configs() -> None:
    """清空全部配置并重植 4 条默认 DeepSeek 供应商。"""
    engine.execute("DELETE FROM model_configs")
    seed_default_model_configs()


def seed_default_model_configs() -> None:
    """首次启动种入默认供应商配置（幂等：仅当表空时）。"""
    if (engine.scalar("SELECT COUNT(*) FROM model_configs") or 0) > 0:
        return
    from app.core.config import get_settings

    s = get_settings()
    defaults = [
        ("deepseek-v4-flash", "DeepSeek V4 Flash", "deepseek-v4-flash", True),
        ("deepseek-v4-chat", "DeepSeek V4 Chat", "deepseek-v4-chat", False),
        ("deepseek-v4-reasoner", "DeepSeek V4 Reasoner", "deepseek-v4-reasoner", False),
        ("deepseek-v4-coder", "DeepSeek V4 Coder", "deepseek-v4-coder", False),
    ]
    for key, name, model_id, is_def in defaults:
        engine.insert(
            "INSERT INTO model_configs (provider_key, display_name, api_key, base_url, protocol, model_ids, is_custom, is_default, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'openai-completions', ?, 0, ?, 1, ?, ?)",
            (key, name, s.dsh_resolved_api_key, s.deepseek_base_url or "https://api.deepseek.com/v1",
             engine.dumps([model_id]),
             1 if is_def else 0, _now(), _now()),
        )
