"""用户存储 SQLite 实现（task/19）：标准库 sqlite3，零新依赖。

每操作独立连接（天然跨线程安全），WAL 日志模式，供认证与会话门控使用。
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from utils import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'teacher',
    plan TEXT NOT NULL DEFAULT 'free', school_id TEXT, avatar TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_users_plan ON users(plan);
"""


class UserStore:
    """标准库 sqlite3 用户数据访问类：WAL 模式、每操作独立连接、with 事务语义。"""

    _INSERT_SQL = (
        "INSERT INTO users (id, username, password_hash, display_name, role, "
        "plan, school_id, avatar, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)"
    )

    def __init__(self, db_path: str = config.USER_DB_PATH) -> None:
        """建父目录并幂等建表建索引，可重复初始化。"""
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

    def create_user(
        self,
        username: str,
        password_hash: str,
        display_name: str = "",
        role: str = "teacher",
        plan: str = "free",
        school_id: str | None = None,
        avatar: str | None = None,
    ) -> dict:
        """插入新用户并返回完整记录；用户名重名抛 sqlite3.IntegrityError。"""
        now = self._now()
        user_id = uuid.uuid4().hex
        with self._session() as conn:
            conn.execute(
                self._INSERT_SQL,
                (user_id, username, password_hash, display_name, role, plan,
                 school_id, avatar, now, now),
            )
        return {
            "id": user_id,
            "username": username,
            "password_hash": password_hash,
            "display_name": display_name,
            "role": role,
            "plan": plan,
            "school_id": school_id,
            "avatar": avatar,
            "created_at": now,
            "updated_at": now,
        }

    def get_user(self, user_id: str) -> dict | None:
        """按主键查单用户，不存在返回 None。"""
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def get_user_by_username(self, username: str) -> dict | None:
        """按用户名查单用户，不存在返回 None。"""
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username=?", (username,)
            ).fetchone()
        return dict(row) if row is not None else None

    def update_plan(self, user_id: str, plan: str) -> None:
        """更新用户套餐；用户不存在抛 ValueError（fail-fast，不静默降级）。"""
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE users SET plan=?, updated_at=? WHERE id=?",
                (plan, self._now(), user_id),
            )
        if cursor.rowcount == 0:
            raise ValueError(f"用户不存在: {user_id}")

    def update_school_id(self, user_id: str, school_id: str) -> None:
        """更新用户所属学校 id；用户不存在抛 ValueError（fail-fast）。"""
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE users SET school_id=?, updated_at=? WHERE id=?",
                (school_id, self._now(), user_id),
            )
        if cursor.rowcount == 0:
            raise ValueError(f"用户不存在: {user_id}")

    def update_role(self, user_id: str, role: str) -> None:
        """更新用户角色；用户不存在抛 ValueError（fail-fast，不静默降级）。"""
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE users SET role=?, updated_at=? WHERE id=?",
                (role, self._now(), user_id),
            )
        if cursor.rowcount == 0:
            raise ValueError(f"用户不存在: {user_id}")

    def list_users_by_school(self, school_id: str) -> list[dict]:
        """按学校 id 列出全部成员，按创建时间倒序。"""
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE school_id=? ORDER BY created_at DESC",
                (school_id,),
            ).fetchall()
        return [dict(row) for row in rows]


_store: UserStore | None = None


def default_user_store() -> UserStore:
    """懒加载并缓存全局共享用户存储单例，供路由与会话门控共用。"""
    global _store
    if _store is None:
        _store = UserStore()
    return _store
