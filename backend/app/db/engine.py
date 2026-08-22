"""轻量数据库引擎：MySQL（pymysql）优先，SQLite（标准库）降级。

设计约定：
- 上层 SQL 统一用 `?` 占位符，engine 内部按方言转换（MySQL → %s）。
- JSON 一律存 TEXT（json.dumps），读取由 repository 反序列化。
- 布尔一律存 0/1 整数。
- 连接每次操作独占（短连接）：分析平台 QPS 低，换来零连接池维护成本；
  SQLite 每线程独立文件连接，避开跨线程复用限制。
- asyncio 场景经 asyncio.to_thread 调用（同步 API）。
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pymysql

from app.core.config import get_settings

_LOCK = threading.Lock()
_READY = False


def _parse_db_url(url: str) -> tuple[str, dict[str, Any]]:
    """解析 AI_NAVIGATOR_DB 形如 mysql://user:pass@host:port/db 或 sqlite:///path。"""
    if url.startswith("sqlite"):
        path = re.sub(r"^sqlite:/{2,3}", "", url) or "dev.db"
        return "sqlite", {"path": path}
    m = re.match(r"mysql(?:\+pymysql)?://([^:]+):([^@]+)@([^:/]+)(?::(\d+))?/([^?]+)", url)
    if not m:
        raise ValueError(f"无法解析数据库连接串：{url}")
    user, password, host, port, db = m.group(1), m.group(2), m.group(3), int(m.group(4) or 3306), m.group(5)
    return "mysql", {"host": host, "port": port, "user": user, "password": password, "database": db}


def _connect() -> tuple[str, Any]:
    url = get_settings().database_url
    kind, params = _parse_db_url(url)
    if kind == "sqlite":
        path = Path(params["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)  # 自动提交
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return kind, conn
    conn = pymysql.connect(
        host=params["host"], port=params["port"], user=params["user"],
        password=params["password"], database=params["database"],
        charset="utf8mb4", autocommit=True,
    )
    return kind, conn


def execute(sql: str, params: tuple | list = ()) -> int:
    """执行写语句，返回受影响行数（INSERT 拿 lastrowid 用 insert()）。"""
    kind, conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql.replace("?", "%s") if kind == "mysql" else sql, params)
        affected, rowid = cur.rowcount, cur.lastrowid
        cur.close()
        return affected
    finally:
        conn.close()


def insert(sql: str, params: tuple | list = ()) -> int:
    """执行插入，返回自增 id。"""
    kind, conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql.replace("?", "%s") if kind == "mysql" else sql, params)
        rowid = cur.lastrowid
        cur.close()
        return int(rowid)
    finally:
        conn.close()


def query(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    """查询并返回 dict 行列表。"""
    kind, conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql.replace("?", "%s") if kind == "mysql" else sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


def query_one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: tuple | list = ()) -> Any:
    kind, conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql.replace("?", "%s") if kind == "mysql" else sql, params)
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    finally:
        conn.close()


def loads(value: Any, default: Any = None) -> Any:
    """JSON 列反序列化（容错）。"""
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def init_schema() -> None:
    """建表（可重复执行）。DDL 方言差异在 entities.py 内维护。"""
    global _READY
    from app.db.entities import SCHEMA_MYSQL, SCHEMA_SQLITE

    with _LOCK:
        if _READY:
            return
        kind, conn = _connect()
        try:
            cur = conn.cursor()
            for stmt in (SCHEMA_MYSQL if kind == "mysql" else SCHEMA_SQLITE):
                cur.execute(stmt)
            cur.close()
        finally:
            conn.close()
        # 已有表补列（assessments.risk/gaps 等，可重复执行）
        from app.db.entities import _migrate_columns

        _migrate_columns()
        # 首次启动种入默认模型供应商配置（幂等）
        from app.db.entities import seed_default_model_configs

        seed_default_model_configs()
        _READY = True
