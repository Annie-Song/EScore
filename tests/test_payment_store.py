"""支付订单存储（services/payment_store.py）单元测试。

全部用例通过 tmp_path 构造临时 db 并显式传 db_path，不触碰真实
output/users.db。覆盖：create_order/get_order/mark_paid/list_orders、
mark_paid 幂等、表结构幂等初始化。
"""
from __future__ import annotations

import sqlite3

import pytest

from services.payment_store import PaymentStore


@pytest.fixture
def store(tmp_path) -> PaymentStore:
    """在 tmp_path 下建空库并返回 PaymentStore 实例。"""
    return PaymentStore(str(tmp_path / "payments.db"))


def test_create_order_returns_full_pending_record(store: PaymentStore) -> None:
    """create_order 返回完整订单：id/user_id/plan/amount/status/gateway。"""
    order = store.create_order("u-1", "pro", 9900, "demo")
    assert order["id"]
    assert order["user_id"] == "u-1"
    assert order["plan"] == "pro"
    assert order["amount_cents"] == 9900
    assert order["status"] == "pending"
    assert order["gateway"] == "demo"
    for key in ("created_at", "updated_at"):
        assert order[key]


def test_get_order_hit_and_miss(store: PaymentStore) -> None:
    """get_order 命中返回订单、未命中返回 None。"""
    created = store.create_order("u-1", "pro", 9900, "demo")
    row = store.get_order(created["id"])
    assert row is not None
    assert row["id"] == created["id"]
    assert row["user_id"] == "u-1"
    assert store.get_order("no-such-order") is None


def test_mark_paid_first_true_then_false_idempotent(
    store: PaymentStore,
) -> None:
    """mark_paid：首次转 paid 返回 True，重复调用返回 False 且状态不变。"""
    order = store.create_order("u-1", "pro", 9900, "demo")
    assert store.mark_paid(order["id"]) is True
    assert store.get_order(order["id"])["status"] == "paid"
    assert store.mark_paid(order["id"]) is False
    assert store.get_order(order["id"])["status"] == "paid"


def test_mark_paid_missing_order_returns_false(store: PaymentStore) -> None:
    """mark_paid 订单不存在：返回 False 不抛错。"""
    assert store.mark_paid("no-such-order") is False


def test_mark_paid_does_not_touch_other_orders(store: PaymentStore) -> None:
    """mark_paid 只更新目标订单，其余订单保持 pending。"""
    order_a = store.create_order("u-1", "pro", 9900, "demo")
    order_b = store.create_order("u-1", "pro", 9900, "demo")
    store.mark_paid(order_a["id"])
    assert store.get_order(order_a["id"])["status"] == "paid"
    assert store.get_order(order_b["id"])["status"] == "pending"


def test_list_orders_only_user_and_desc_by_created_at(
    tmp_path, monkeypatch,
) -> None:
    """list_orders 只返回指定用户订单，按 created_at 倒序。"""
    store = PaymentStore(str(tmp_path / "order.db"))
    now = iter(["2026-01-01T00:00:01", "2026-01-01T00:00:02",
                "2026-01-01T00:00:03"])
    monkeypatch.setattr(store, "_now", lambda: next(now))
    order_first = store.create_order("u-1", "pro", 9900, "demo")
    order_second = store.create_order("u-1", "pro", 9900, "demo")
    store.create_order("u-2", "pro", 9900, "demo")  # 其他用户，不应出现
    rows = store.list_orders("u-1")
    assert [r["id"] for r in rows] == [order_second["id"], order_first["id"]]


def test_table_init_idempotent(tmp_path) -> None:
    """同一路径重复初始化不报错、不重建（表结构幂等）。"""
    db_path = str(tmp_path / "reinit.db")
    PaymentStore(db_path)
    PaymentStore(db_path)
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert "payments" in tables


def test_wal_mode_enabled(tmp_path) -> None:
    """初始化后 PRAGMA journal_mode 应为 wal。"""
    db_path = str(tmp_path / "wal.db")
    PaymentStore(db_path)
    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode == "wal"
