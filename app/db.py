"""SQLite 元数据库：客户、项目、交付物、文件版本、处理任务、操作记录、规则。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_types (
    code TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    stage TEXT DEFAULT '',
    kw TEXT DEFAULT '[]',
    series INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    builtin INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS source_seen (
    path TEXT PRIMARY KEY,
    size INTEGER,
    mtime REAL,
    source_id TEXT,
    job_id INTEGER,
    seen_at TEXT
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    short_name TEXT NOT NULL,
    full_name TEXT DEFAULT '',
    aliases TEXT DEFAULT '[]',
    dir_name TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS customer_merges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT DEFAULT '',
    short_name TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    target_id INTEGER NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_no TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    biz_line TEXT DEFAULT '',
    status TEXT DEFAULT '进行中',
    start_date TEXT DEFAULT '',
    end_date TEXT DEFAULT '',
    keywords TEXT DEFAULT '[]',
    dir_name TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    title TEXT NOT NULL,
    current_version TEXT DEFAULT 'V1.0',
    status TEXT DEFAULT '正式',
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    document_id INTEGER,
    project_id INTEGER,
    doc_type TEXT,
    version TEXT,
    status TEXT,
    archive_name TEXT,
    archive_path TEXT,
    original_name TEXT,
    source TEXT,
    sha256 TEXT,
    size INTEGER,
    doc_date TEXT,
    title TEXT,
    summary TEXT DEFAULT '',
    snippet TEXT DEFAULT '',
    sensitivity TEXT DEFAULT '一般',
    state TEXT DEFAULT 'archived',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_sha ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(archive_path);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT,
    original_path TEXT,
    staged_path TEXT,
    source TEXT,
    batch_id TEXT,
    sha256 TEXT,
    size INTEGER,
    status TEXT,
    method TEXT,
    confidence REAL,
    suggestion TEXT DEFAULT '{}',
    result TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    file_id INTEGER,
    created_at TEXT,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    kind TEXT,
    src TEXT,
    dst TEXT,
    data TEXT DEFAULT '{}',
    undone INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    doc_type TEXT DEFAULT '',
    hits INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    provider TEXT,
    request TEXT,
    response TEXT,
    ms INTEGER,
    ok INTEGER,
    created_at TEXT
);
"""


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()
            self._migrate()

    def _migrate(self) -> None:
        """旧版数据库升级：只增加字段，不改动已有数据。"""
        cols = {r["name"] for r in self.q("PRAGMA table_info(rules)")}
        if "kind" not in cols:
            self.x("ALTER TABLE rules ADD COLUMN kind TEXT DEFAULT 'project'")
        if "source" not in cols:
            self.x("ALTER TABLE rules ADD COLUMN source TEXT DEFAULT 'manual'")

    def q(self, sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> Optional[Dict[str, Any]]:
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def insert(self, table: str, row: Dict[str, Any]) -> int:
        cols = list(row.keys())
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        return self.x(sql, tuple(_enc(row[c]) for c in cols))

    def update(self, table: str, row_id: int, changes: Dict[str, Any]) -> None:
        if not changes:
            return
        sets = ",".join(f"{k}=?" for k in changes)
        self.x(f"UPDATE {table} SET {sets} WHERE id=?", tuple(_enc(v) for v in changes.values()) + (row_id,))


def _enc(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def loads(s: Any, default: Any = None) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except Exception:
        return default
