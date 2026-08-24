"""支付宝沙箱网关单元测试（F5）。

全部用例 mock alipay SDK 模块（sys.modules 注入假 AliPay），不触发真实
网络与 SDK 调用。覆盖：
1. is_configured：配置缺省为 False、齐全为 True。
2. 配置缺失构造抛 RuntimeError（消息含缺失配置项名）。
3. SDK 未安装（import 失败）构造抛清晰 RuntimeError。
4. create_order 调 alipay.direct_pay 组链接、金额分转元两位小数。
5. verify_callback 调 alipay.verify 并剔除 sign/sign_type。
6. parse_callback 提取 out_trade_no 与 TRADE_SUCCESS 状态。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from backend.pay.alipay import AlipaySandboxGateway
from backend.core import config

# 启用的三个必需配置项键名（缺省空串即未配置）
_CONFIG_KEYS = ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY")


class _FakeClient:
    """假支付宝客户端：记录 direct_pay/verify 调用入参。"""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def direct_pay(self, **kwargs: Any) -> str:
        self.last_direct_pay = kwargs
        return "out_trade_no=order-1&sign=abc"

    def verify(self, data: dict, signature: str) -> bool:
        self.last_verify = (data, signature)
        return True


class _FakeAliPay:
    """假 AliPay 工厂：任何构造参数都返回假客户端。"""

    def __new__(cls, *args: Any, **kwargs: Any) -> _FakeClient:
        return _FakeClient()


def _set_config(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """把支付宝三个必需配置项统一设为指定值。"""
    for key in _CONFIG_KEYS:
        monkeypatch.setattr(config, key, value)


def _inject_fake_alipay(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 sys.modules['alipay'] 替换为假模块，隔离真实 SDK。"""
    fake_module = SimpleNamespace(AliPay=_FakeAliPay)
    monkeypatch.setitem(sys.modules, "alipay", fake_module)


def _make_gateway(monkeypatch: pytest.MonkeyPatch) -> AlipaySandboxGateway:
    """构造配置齐全 + SDK 被 mock 的沙箱网关。"""
    _set_config(monkeypatch, "test-value")
    _inject_fake_alipay(monkeypatch)
    return AlipaySandboxGateway()


def test_is_configured_false_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三个必需配置项缺省为空：is_configured 返回 False。"""
    _set_config(monkeypatch, "")
    assert AlipaySandboxGateway.is_configured() is False


def test_is_configured_true_when_all_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三个必需配置项全非空：is_configured 返回 True。"""
    _set_config(monkeypatch, "some-value")
    assert AlipaySandboxGateway.is_configured() is True


def test_is_configured_partial_env_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅部分配置项非空：is_configured 返回 False。"""
    _set_config(monkeypatch, "")
    monkeypatch.setattr(config, "ALIPAY_APP_ID", "app-id-only")
    assert AlipaySandboxGateway.is_configured() is False


def test_init_raises_runtime_error_when_config_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置缺失构造：抛 RuntimeError 且消息列出缺失项名。"""
    _set_config(monkeypatch, "")
    with pytest.raises(RuntimeError) as excinfo:
        AlipaySandboxGateway()
    message = str(excinfo.value)
    assert "配置缺失" in message
    assert "ALIPAY_APP_ID" in message
    assert "ALIPAY_PRIVATE_KEY" in message


def test_init_raises_clear_error_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置齐全但 SDK 未安装（import 失败）：抛 RuntimeError 且提示安装。"""
    _set_config(monkeypatch, "test-value")
    monkeypatch.setitem(sys.modules, "alipay", None)
    with pytest.raises(RuntimeError) as excinfo:
        AlipaySandboxGateway()
    assert "未安装" in str(excinfo.value)


def test_create_order_calls_direct_pay_and_builds_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_order：调 direct_pay，金额分转元两位小数，返回网关 URL+查询串。"""
    gateway = _make_gateway(monkeypatch)
    client = gateway._client
    url = gateway.create_order("order-1", 9900, "升级专业版")
    assert url == config.ALIPAY_GATEWAY_URL + "?out_trade_no=order-1&sign=abc"
    kwargs = client.last_direct_pay
    assert kwargs["out_trade_no"] == "order-1"
    assert kwargs["subject"] == "升级专业版"
    assert kwargs["total_amount"] == "99.00"
    assert kwargs["return_url"] == config.PAY_RETURN_URL
    assert kwargs["notify_url"] == config.PAY_NOTIFY_URL


def test_create_order_amount_cents_two_decimals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """金额 1 分 → '0.01'；非整元保留两位小数。"""
    gateway = _make_gateway(monkeypatch)
    gateway.create_order("order-1", 1, "subject")
    assert gateway._client.last_direct_pay["total_amount"] == "0.01"


def test_verify_callback_calls_verify_with_cleaned_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """verify_callback：剔除 sign/sign_type 后调 verify，返回其结果。"""
    gateway = _make_gateway(monkeypatch)
    client = gateway._client
    params = {
        "out_trade_no": "order-1",
        "trade_status": "TRADE_SUCCESS",
        "sign": "sig",
        "sign_type": "RSA2",
    }
    assert gateway.verify_callback(params) is True
    data, signature = client.last_verify
    assert signature == "sig"
    assert data == {"out_trade_no": "order-1", "trade_status": "TRADE_SUCCESS"}
    assert "sign" not in data
    assert "sign_type" not in data


def test_parse_callback_extracts_order_and_success() -> None:
    """parse_callback：TRADE_SUCCESS → success True，其他状态 → False。

    解析逻辑只依赖 params 不触碰 _client，直接用 __new__ 构造实例即可。
    """
    gateway = AlipaySandboxGateway.__new__(AlipaySandboxGateway)
    parsed_ok = gateway.parse_callback({
        "out_trade_no": "order-1",
        "trade_status": "TRADE_SUCCESS",
    })
    assert parsed_ok == {"order_id": "order-1", "success": True}
    parsed_fail = gateway.parse_callback({
        "out_trade_no": "order-2",
        "trade_status": "TRADE_FINISHED",
    })
    assert parsed_fail == {"order_id": "order-2", "success": False}
    parsed_empty = gateway.parse_callback({})
    assert parsed_empty == {"order_id": None, "success": False}
