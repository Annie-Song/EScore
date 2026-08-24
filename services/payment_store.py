"""支付订单存储 SQLite 实现（F5）：镜像 user_store 模式，存 users.db。

每操作独立连接（天然跨线程安全），WAL 日志模式，标准库 sqlite3 零新依赖。
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
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, plan TEXT NOT NULL,
    amount_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    gateway TEXT NOT NULL DEFAULT 'demo', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
"""


class PaymentStore:
    """标准库 sqlite3 支付订单数据访问类：WAL 模式、每操作独立连接、with 事务语义。"""

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

    def create_order(self, user_id: str, plan: str, amount_cents: int, gateway: str) -> dict:
        """创建待支付订单，返回完整订单字典。"""
        now = self._now()
        order_id = uuid.uuid4().hex
        with self._session() as conn:
            conn.execute(
                "INSERT INTO payments "
                "(id, user_id, plan, amount_cents, status, gateway, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (order_id, user_id, plan, amount_cents, "pending", gateway, now, now),
            )
        return self.get_order(order_id)

    def get_order(self, order_id: str) -> dict | None:
        """按主键查单订单，不存在返回 None。"""
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE id=?", (order_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_paid(self, order_id: str) -> bool:
        """把待支付订单置为已支付；幂等：已是 paid 返回 False，本次转 paid 返回 True。"""
        with self._session() as conn:
            cursor = conn.execute(
                "UPDATE payments SET status='paid', updated_at=? "
                "WHERE id=? AND status='pending'",
                (self._now(), order_id),
            )
        return cursor.rowcount == 1

    def list_orders(self, user_id: str) -> list[dict]:
        """列出用户全部订单，按创建时间倒序。"""
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]


_store: PaymentStore | None = None


def default_payment_store() -> PaymentStore:
    """懒加载并缓存全局共享支付订单存储单例，供支付路由共用。"""
    global _store
    if _store is None:
        _store = PaymentStore()
    return _store
