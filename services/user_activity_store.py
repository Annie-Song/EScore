"""用户行为存储 SQLite 实现（task/19）：批次关联 + 题目收藏。

每操作独立连接（天然跨线程安全），WAL 日志模式，标准库 sqlite3 零新依赖。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from utils import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_batches (
    user_id TEXT NOT NULL, task_id TEXT NOT NULL UNIQUE, batch_id TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY (user_id, batch_id));
CREATE TABLE IF NOT EXISTS user_favorites (
    user_id TEXT NOT NULL, qid TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '',
    qtype TEXT NOT NULL DEFAULT '', question TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, PRIMARY KEY (user_id, qid));
"""


class UserActivityStore:
    """标准库 sqlite3 用户行为数据访问类：WAL 模式、每操作独立连接、with 事务语义。"""

    def __init__(self, db_path: str = config.USER_DB_PATH) -> None:
        """建父目录并幂等建表，可重复初始化。"""
        self._db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._session() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """开新连接：设置行工厂并启用 WAL 日志模式。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """事务会话：正常提交、异常回滚，退出时关闭连接。"""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _now(self) -> str:
        """返回当前时间的 ISO 格式字符串。"""
        return datetime.now().isoformat()

    def link_batch(self, user_id: str, task_id: str, batch_id: str) -> None:
        """将批改批次关联到用户（INSERT OR REPLACE，幂等）。"""
        with self._session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_batches "
                "(user_id, task_id, batch_id, created_at) VALUES (?,?,?,?)",
                (user_id, task_id, batch_id, self._now()),
            )

    def list_user_batches(self, user_id: str) -> list[dict]:
        """列出用户全部关联批次，按创建时间倒序。"""
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM user_batches WHERE user_id=? "
                "ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_all_batches(self) -> list[dict]:
        """列出全部用户-批次关联映射（跨校管理用），按创建时间倒序。"""
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM user_batches ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_favorite(
        self,
        user_id: str,
        qid: str,
        subject: str = "",
        qtype: str = "",
        question: str = "",
        score: int = 0,
    ) -> bool:
        """收藏题目（INSERT OR IGNORE），返回是否新插入。"""
        with self._session() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO user_favorites "
                "(user_id, qid, subject, qtype, question, score, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (user_id, qid, subject, qtype, question, score, self._now()),
            )
        return cursor.rowcount == 1

    def remove_favorite(self, user_id: str, qid: str) -> bool:
        """取消收藏题目，返回是否删除到记录。"""
        with self._session() as conn:
            cursor = conn.execute(
                "DELETE FROM user_favorites WHERE user_id=? AND qid=?",
                (user_id, qid),
            )
        return cursor.rowcount == 1

    def list_favorites(self, user_id: str) -> list[dict]:
        """列出用户全部收藏题目，按创建时间倒序。"""
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM user_favorites WHERE user_id=? "
                "ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]


_store: UserActivityStore | None = None


def default_user_activity_store() -> UserActivityStore:
    """懒加载并缓存全局共享用户行为存储单例，供路由共用。"""
    global _store
    if _store is None:
        _store = UserActivityStore()
    return _store
