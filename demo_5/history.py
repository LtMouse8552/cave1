"""
会话历史存储（SQLite）
======================

Deep Agents 的检查点（data/checkpoints.db）保存的是 Agent 的“工作记忆”：
完整消息、待办、文件等，用于让模型接着上下文继续回答。

本模块另外保存一份“给人看的”聊天记录（data/sessions.db）：
每个会话的标题、时间，以及每条消息和它的执行步骤，用于在界面上列出和回放历史会话。

两者通过同一个 thread_id 关联：
    界面选中某个历史会话  ->  拿到 thread_id  ->  用它继续调用 Agent  ->  模型能看到之前的上下文
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime

from agent import DATA_DIR

DB_PATH = DATA_DIR / "sessions.db"


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            thread_id  TEXT PRIMARY KEY,
            title      TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id  TEXT NOT NULL,
            role       TEXT NOT NULL,          -- user / assistant
            content    TEXT NOT NULL,
            steps      TEXT NOT NULL DEFAULT '[]',  -- 执行步骤 JSON
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, id);
        """
    )
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_thread_id() -> str:
    return str(uuid.uuid4())


def save_message(thread_id: str, role: str, content: str, steps: list | None = None) -> None:
    """追加一条消息；如果是会话的第一条消息，用它的前 30 个字作为会话标题。"""
    with _conn() as conn:
        now = _now()
        title = content.strip().replace("\n", " ")[:30] or "新会话"
        conn.execute(
            "INSERT INTO sessions(thread_id, title, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(thread_id) DO UPDATE SET updated_at = excluded.updated_at",
            (thread_id, title, now, now),
        )
        conn.execute(
            "INSERT INTO messages(thread_id, role, content, steps, created_at) VALUES (?, ?, ?, ?, ?)",
            (thread_id, role, content, json.dumps(steps or [], ensure_ascii=False), now),
        )


def list_sessions(limit: int = 50) -> list[dict]:
    """按最近更新时间倒序列出会话。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT s.thread_id, s.title, s.updated_at, COUNT(m.id) AS n "
            "FROM sessions s LEFT JOIN messages m ON m.thread_id = s.thread_id "
            "GROUP BY s.thread_id ORDER BY s.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_messages(thread_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content, steps FROM messages WHERE thread_id = ? ORDER BY id", (thread_id,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"], "steps": json.loads(r["steps"])} for r in rows]


def rename_session(thread_id: str, title: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE sessions SET title = ? WHERE thread_id = ?", (title.strip() or "未命名", thread_id))


def delete_session(thread_id: str) -> None:
    """删除会话的聊天记录。Agent 检查点需另外调用 checkpointer.adelete_thread() 删除（web.py 中已处理）。"""
    with _conn() as conn:
        conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
        conn.execute("DELETE FROM sessions WHERE thread_id = ?", (thread_id,))
