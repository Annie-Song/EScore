"""专业版升级与支付闭环 Flask 路由单元测试（F5）。

覆盖 /upgrade、POST /api/pay/orders、GET /api/pay/demo/confirm、
POST /api/pay/notify、GET /api/pay/status/<order_id> 五类接口：
游客 401、非法套餐 400、订单创建 201、演示回调校验/幂等升级、
异步通知验签成功幂等/失败返回 fail、订单归属校验 403。

存储隔离：monkeypatch pay_routes.default_payment_store /
default_user_store 指向 tmp_path 临时库；支付宝配置固定为空串确保走
本地演示网关；异步通知用假网关 mock verify_callback/parse_callback。
离线独立运行，不触碰真实 output/*.db 与 SDK。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import backend.pay.routes as pay_routes
from backend.app import create_app
from backend.pay.gateway import _demo_token
from backend.pay.store import PaymentStore
from backend.auth.store import UserStore
from backend.core import config

USER_ID = "u-pay-1"
_ALIPAY_KEYS = ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY")


class _FakeGateway:
    """假支付网关：异步通知测试用，可控 verify_callback/parse_callback。"""

    def __init__(
        self, verify_result: bool = True, parsed: dict | None = None
    ) -> None:
        self.verify_result = verify_result
        self.parsed = parsed or {"order_id": "", "success": True}
        self.last_params: dict | None = None

    def verify_callback(self, params: dict) -> bool:
        self.last_params = params
        return self.verify_result

    def parse_callback(self, params: dict) -> dict:
        return self.parsed


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Any:
    """隔离存储的测试上下文：支付库/用户库指向 tmp，支付宝配置置空。"""
    payment_store = PaymentStore(str(tmp_path / "payments.db"))
    user_store = UserStore(str(tmp_path / "users.db"))
    monkeypatch.setattr(
        pay_routes, "default_payment_store", lambda: payment_store
    )
    monkeypatch.setattr(pay_routes, "default_user_store", lambda: user_store)
    for key in _ALIPAY_KEYS:
        monkeypatch.setattr(config, key, "")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield SimpleNamespace(
            client=client, payment=payment_store, users=user_store
        )


def _make_user(ctx: Any, plan: str = "free") -> dict:
    """在隔离用户库创建用户并返回记录。"""
    return ctx.users.create_user("alice", "hash", plan=plan)


def _login(ctx: Any, user_id: str) -> None:
    """写入会话 user_id 模拟登录态。"""
    with ctx.client.session_transaction() as sess:
        sess["user_id"] = user_id


def _demo_confirm_url(order_id: str) -> str:
    """构造本地演示确认回调完整 URL。"""
    return (
        f"/api/pay/demo/confirm?order_id={order_id}"
        f"&token={_demo_token(order_id)}"
    )


def _spy_update_plan(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> list:
    """包装 user_store.update_plan 计数调用次数，返回记录列表。"""
    calls: list = []
    original = ctx.users.update_plan

    def spy(user_id: str, plan: str) -> None:
        calls.append((user_id, plan))
        original(user_id, plan)

    monkeypatch.setattr(ctx.users, "update_plan", spy)
    return calls


# ---------- /upgrade 页面 ----------


def test_upgrade_page_renders_200(ctx: Any) -> None:
    """GET /upgrade：200 且渲染出升级页关键文案。"""
    resp = ctx.client.get("/upgrade")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "升级专业版" in html
    assert 'id="upgradeBtn"' in html


# ---------- POST /api/pay/orders ----------


def test_create_order_guest_401(ctx: Any) -> None:
    """游客 POST /api/pay/orders：401 请先登录。"""
    resp = ctx.client.post("/api/pay/orders", json={"plan": "pro"})
    assert resp.status_code == 401


def test_create_order_logged_in_returns_201_demo_gateway(ctx: Any) -> None:
    """登录用户 POST pro：201，返回 order_id+pay_url+gateway=demo。"""
    user = _make_user(ctx)
    _login(ctx, user["id"])
    resp = ctx.client.post("/api/pay/orders", json={"plan": "pro"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["order_id"]
    assert body["gateway"] == "demo"
    assert body["order_id"] in body["pay_url"]
    assert "/api/pay/demo/confirm" in body["pay_url"]
    order = ctx.payment.get_order(body["order_id"])
    assert order is not None
    assert order["status"] == "pending"
    assert order["user_id"] == user["id"]


def test_create_order_invalid_plan_400(ctx: Any) -> None:
    """登录用户提交非法套餐：400 不支持的套餐，且不创建订单。"""
    user = _make_user(ctx)
    _login(ctx, user["id"])
    resp = ctx.client.post("/api/pay/orders", json={"plan": "ultra"})
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "不支持的套餐"
    assert ctx.payment.list_orders(user["id"]) == []


# ---------- GET /api/pay/demo/confirm ----------


def test_demo_confirm_valid_upgrades_plan_and_redirects(ctx: Any) -> None:
    """合法演示回调：升级 plan、订单置 paid、302 到 /me?upgraded=1。"""
    user = _make_user(ctx, plan="free")
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    _login(ctx, user["id"])
    resp = ctx.client.get(_demo_confirm_url(order["id"]))
    assert resp.status_code == 302
    assert "/me?upgraded=1" in resp.headers["Location"]
    assert ctx.users.get_user(user["id"])["plan"] == "pro"
    assert ctx.payment.get_order(order["id"])["status"] == "paid"
    with ctx.client.session_transaction() as sess:
        assert sess["plan"] == "pro"


def test_demo_confirm_invalid_token_no_upgrade(ctx: Any) -> None:
    """非法令牌：400，plan 不变、订单仍 pending。"""
    user = _make_user(ctx, plan="free")
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    _login(ctx, user["id"])
    url = f"/api/pay/demo/confirm?order_id={order['id']}&token=bad-token"
    resp = ctx.client.get(url)
    assert resp.status_code == 400
    assert ctx.users.get_user(user["id"])["plan"] == "free"
    assert ctx.payment.get_order(order["id"])["status"] == "pending"


def test_demo_confirm_order_not_found_404(ctx: Any) -> None:
    """合法令牌但订单不存在：404 订单不存在。"""
    user = _make_user(ctx)
    _login(ctx, user["id"])
    resp = ctx.client.get(_demo_confirm_url("no-such-order"))
    assert resp.status_code == 404


def test_demo_confirm_replay_no_duplicate_upgrade(
    ctx: Any, monkeypatch,
) -> None:
    """回调重放：不重复升级（update_plan 仅调用一次），订单保持 paid。"""
    user = _make_user(ctx, plan="free")
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    _login(ctx, user["id"])
    calls = _spy_update_plan(ctx, monkeypatch)
    url = _demo_confirm_url(order["id"])
    assert ctx.client.get(url).status_code == 302
    assert ctx.client.get(url).status_code == 302
    assert len(calls) == 1
    assert ctx.payment.get_order(order["id"])["status"] == "paid"
    assert ctx.users.get_user(user["id"])["plan"] == "pro"


# ---------- POST /api/pay/notify ----------


def test_notify_valid_signature_upgrades_plan(ctx: Any, monkeypatch) -> None:
    """异步通知验签通过：200 'success'，订单 paid、plan 升级。"""
    user = _make_user(ctx, plan="free")
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    fake = _FakeGateway(parsed={"order_id": order["id"], "success": True})
    monkeypatch.setattr(pay_routes, "get_active_gateway", lambda: fake)
    resp = ctx.client.post("/api/pay/notify", data={
        "out_trade_no": order["id"],
        "trade_status": "TRADE_SUCCESS",
    })
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "success"
    assert ctx.payment.get_order(order["id"])["status"] == "paid"
    assert ctx.users.get_user(user["id"])["plan"] == "pro"


def test_notify_replay_idempotent(ctx: Any, monkeypatch) -> None:
    """异步通知重放：update_plan 仅调用一次，不重复升级。"""
    user = _make_user(ctx, plan="free")
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    fake = _FakeGateway(parsed={"order_id": order["id"], "success": True})
    monkeypatch.setattr(pay_routes, "get_active_gateway", lambda: fake)
    calls = _spy_update_plan(ctx, monkeypatch)
    for _ in range(2):
        resp = ctx.client.post("/api/pay/notify", data={
            "out_trade_no": order["id"], "trade_status": "TRADE_SUCCESS",
        })
        assert resp.get_data(as_text=True) == "success"
    assert len(calls) == 1


def test_notify_bad_signature_returns_fail(ctx: Any, monkeypatch) -> None:
    """验签失败：200 'fail'，订单不置 paid。"""
    user = _make_user(ctx)
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    fake = _FakeGateway(verify_result=False)
    monkeypatch.setattr(pay_routes, "get_active_gateway", lambda: fake)
    resp = ctx.client.post(
        "/api/pay/notify", data={"out_trade_no": order["id"]}
    )
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "fail"
    assert ctx.payment.get_order(order["id"])["status"] == "pending"


def test_notify_success_false_returns_success_no_upgrade(
    ctx: Any, monkeypatch,
) -> None:
    """交易未成功（success False）：200 'success'，不升级。"""
    user = _make_user(ctx, plan="free")
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    fake = _FakeGateway(parsed={"order_id": order["id"], "success": False})
    monkeypatch.setattr(pay_routes, "get_active_gateway", lambda: fake)
    resp = ctx.client.post(
        "/api/pay/notify", data={"out_trade_no": order["id"]}
    )
    assert resp.get_data(as_text=True) == "success"
    assert ctx.payment.get_order(order["id"])["status"] == "pending"
    assert ctx.users.get_user(user["id"])["plan"] == "free"


def test_notify_order_missing_returns_fail(ctx: Any, monkeypatch) -> None:
    """通知引用不存在的订单：200 'fail'（让支付平台重试）。"""
    fake = _FakeGateway(parsed={"order_id": "no-such-order", "success": True})
    monkeypatch.setattr(pay_routes, "get_active_gateway", lambda: fake)
    resp = ctx.client.post(
        "/api/pay/notify", data={"out_trade_no": "no-such-order"}
    )
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "fail"


# ---------- GET /api/pay/status/<order_id> ----------


def test_status_guest_401(ctx: Any) -> None:
    """游客 GET /api/pay/status/<id>：401。"""
    order = ctx.payment.create_order("u-x", "pro", 9900, "demo")
    assert ctx.client.get(f"/api/pay/status/{order['id']}").status_code == 401


def test_status_owner_returns_pending(ctx: Any) -> None:
    """登录用户查询自己订单：200，返回 status=pending 与 plan。"""
    user = _make_user(ctx)
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    _login(ctx, user["id"])
    resp = ctx.client.get(f"/api/pay/status/{order['id']}")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "pending", "plan": "pro"}


def test_status_after_paid(ctx: Any) -> None:
    """已支付订单状态返回 paid。"""
    user = _make_user(ctx)
    order = ctx.payment.create_order(user["id"], "pro", 9900, "demo")
    ctx.payment.mark_paid(order["id"])
    _login(ctx, user["id"])
    resp = ctx.client.get(f"/api/pay/status/{order['id']}")
    assert resp.get_json()["status"] == "paid"


def test_status_other_user_403(ctx: Any) -> None:
    """查询他人订单：403 无权查看。"""
    order = ctx.payment.create_order("u-owner", "pro", 9900, "demo")
    user = _make_user(ctx)
    _login(ctx, user["id"])
    resp = ctx.client.get(f"/api/pay/status/{order['id']}")
    assert resp.status_code == 403


def test_status_missing_404(ctx: Any) -> None:
    """订单不存在：404。"""
    user = _make_user(ctx)
    _login(ctx, user["id"])
    assert ctx.client.get("/api/pay/status/no-such-order").status_code == 404
