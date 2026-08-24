"""学校存储 SQLite 实现（F5）：学校维度数据隔离，存 users.db。

镜像 user_store 模式：每操作独立连接、WAL 日志模式、标准库 sqlite3 零新依赖。
school_batch_stats 联查 grades.db（services.store.default_store）聚合批改统计。
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from services.store import default_store
from utils import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schools (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL);
"""


class SchoolStore:
    """标准库 sqlite3 学校数据访问类：WAL 模式、每操作独立连接、with 事务语义。"""

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

    def create_school(self, name: str, code: str, school_id: str | None = None) -> dict:
        """新建学校并返回记录；code 重名抛 sqlite3.IntegrityError。"""
        now = self._now()
        school_id = school_id or uuid.uuid4().hex
        with self._session() as conn:
            conn.execute(
                "INSERT INTO schools (id, name, code, created_at) VALUES (?,?,?,?)",
                (school_id, name, code, now),
            )
        return {"id": school_id, "name": name, "code": code, "created_at": now}

    def get_school(self, school_id: str) -> dict | None:
        """按主键查单学校，不存在返回 None。"""
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM schools WHERE id=?", (school_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def get_school_by_code(self, code: str) -> dict | None:
        """按学校代码查单学校，不存在返回 None。"""
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM schools WHERE code=?", (code,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_schools(self) -> list[dict]:
        """列出全部学校，附成员数联查，按创建时间倒序。"""
        with self._session() as conn:
            rows = conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM users u WHERE u.school_id=s.id) "
                "AS member_count FROM schools s ORDER BY s.created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def school_batch_stats(self, school_id: str) -> dict:
        """联查 users→user_batches→grades.db 聚合：批次数、记录数、平均分。

        数据量小，逐批次 N+1 查询 grades.db 可接受；缺失批次跳过。
        """
        with self._session() as conn:
            rows = conn.execute(
                "SELECT ub.batch_id FROM user_batches ub "
                "JOIN users u ON u.id = ub.user_id WHERE u.school_id=?",
                (school_id,),
            ).fetchall()
        store = default_store()
        batch_count = 0
        record_count = 0
        total_score = 0.0
        for row in rows:
            batch = store.get_batch(row["batch_id"])
            if batch is None:
                continue
            records = store.list_records(row["batch_id"])
            batch_count += 1
            record_count += len(records)
            total_score += sum(record.score for record in records)
        return {
            "batch_count": batch_count,
            "record_count": record_count,
            "avg_score": round(total_score / record_count, 1) if record_count else 0.0,
        }


_store: SchoolStore | None = None


def default_school_store() -> SchoolStore:
    """懒加载并缓存全局共享学校存储单例，供注册与学校路由共用。"""
    global _store
    if _store is None:
        _store = SchoolStore()
    return _store
