"""可插拔支付网关抽象与本地演示网关单元测试（F5）。

覆盖 services/payment.py 三块：
1. LocalDemoGateway 三契约：create_order 生成本地演示 URL、verify_callback
   校验派生令牌、parse_callback 返回成功状态。
2. get_active_gateway 选择逻辑：支付宝未配置 → LocalDemoGateway；配置齐全
   → AlipaySandboxGateway；支付宝初始化失败 → 回退 LocalDemoGateway。
3. 抽象基类 PaymentGateway 定义 create_order/verify_callback/parse_callback 契约。

支付宝配置均经 monkeypatch 固定为空或注入假配置，测试离线独立运行，
不触碰真实 SDK 与网络。
"""
from __future__ import annotations

import pytest

import backend.pay.alipay as alipay_gateway
from backend.pay.gateway import (
    LocalDemoGateway,
    PaymentGateway,
    _demo_token,
    get_active_gateway,
)
from backend.core import config


class _FakeAlipayGateway:
    """测试用假支付宝网关：仅标记 is_configured 为真，构造不触真实 SDK。"""

    name = "alipay"

    @classmethod
    def is_configured(cls) -> bool:
        return True

    def __init__(self) -> None:
        pass


class _FailingAlipayGateway:
    """is_configured 为真但构造抛 RuntimeError 的假网关，用于验证回退。"""

    @classmethod
    def is_configured(cls) -> bool:
        return True

    def __init__(self) -> None:
        raise RuntimeError("boom")


def _clear_alipay_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """把支付宝三个必需配置项固定为空串，保证走本地演示网关。"""
    monkeypatch.setattr(config, "ALIPAY_APP_ID", "")
    monkeypatch.setattr(config, "ALIPAY_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "ALIPAY_PUBLIC_KEY", "")


def test_abstract_gateway_defines_three_contracts() -> None:
    """PaymentGateway 声明 create_order/verify_callback/parse_callback 抽象方法。"""
    for method in ("create_order", "verify_callback", "parse_callback"):
        assert hasattr(PaymentGateway, method)


def test_local_demo_create_order_returns_url_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_order 返回本地演示确认 URL，含 order_id 与派生令牌。"""
    monkeypatch.setattr(
        config, "PAY_RETURN_URL", "http://127.0.0.1:5000/api/pay/return"
    )
    gateway = LocalDemoGateway()
    url = gateway.create_order("order-123", 9900, "升级专业版")
    assert url.startswith("http://127.0.0.1:5000/api/pay/demo/confirm?")
    assert "order_id=order-123" in url
    assert f"token={_demo_token('order-123')}" in url


def test_local_demo_create_order_base_from_return_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PAY_RETURN_URL 改变时演示 URL 前缀同步变化（截取 /api/pay/return 前段）。"""
    monkeypatch.setattr(
        config,
        "PAY_RETURN_URL",
        "https://example.com/custom/path/api/pay/return",
    )
    url = LocalDemoGateway().create_order("order-9", 100, "subject")
    assert url.startswith(
        "https://example.com/custom/path/api/pay/demo/confirm?"
    )


def test_local_demo_verify_callback_valid_token() -> None:
    """正确派生令牌校验通过。"""
    order_id = "order-abc"
    assert LocalDemoGateway().verify_callback(
        {"order_id": order_id, "token": _demo_token(order_id)}
    ) is True


def test_local_demo_verify_callback_invalid_token() -> None:
    """错误令牌校验失败。"""
    assert LocalDemoGateway().verify_callback(
        {"order_id": "order-abc", "token": "bad-token"}
    ) is False


def test_local_demo_verify_callback_missing_params() -> None:
    """缺 order_id 或 token 均校验失败，不抛异常。"""
    gateway = LocalDemoGateway()
    assert gateway.verify_callback({}) is False
    assert gateway.verify_callback({"order_id": "order-abc"}) is False
    assert gateway.verify_callback(
        {"token": _demo_token("order-abc")}
    ) is False


def test_local_demo_parse_callback_returns_success() -> None:
    """parse_callback 原样返回 order_id 且 success 恒为 True。"""
    result = LocalDemoGateway().parse_callback({"order_id": "order-xyz"})
    assert result == {"order_id": "order-xyz", "success": True}


def test_get_active_gateway_returns_local_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """支付宝配置缺失：get_active_gateway 返回 LocalDemoGateway。"""
    _clear_alipay_config(monkeypatch)
    gateway = get_active_gateway()
    assert isinstance(gateway, LocalDemoGateway)


def test_get_active_gateway_returns_alipay_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """支付宝配置齐全：get_active_gateway 返回 AlipaySandboxGateway。"""
    _clear_alipay_config(monkeypatch)
    monkeypatch.setattr(
        alipay_gateway, "AlipaySandboxGateway", _FakeAlipayGateway
    )
    gateway = get_active_gateway()
    assert isinstance(gateway, _FakeAlipayGateway)


def test_get_active_gateway_falls_back_when_alipay_init_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """支付宝配置齐全但网关初始化抛 RuntimeError：回退 LocalDemoGateway。"""
    _clear_alipay_config(monkeypatch)
    monkeypatch.setattr(
        alipay_gateway, "AlipaySandboxGateway", _FailingAlipayGateway
    )
    gateway = get_active_gateway()
    assert isinstance(gateway, LocalDemoGateway)


def test_demo_token_deterministic() -> None:
    """同一订单号派生令牌确定且可复现。"""
    assert _demo_token("order-1") == _demo_token("order-1")
    assert _demo_token("order-1") != _demo_token("order-2")
