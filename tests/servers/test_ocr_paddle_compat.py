"""servers/ocr/paddle_compat.py 兼容垫片的单元测试。

用注入的假 paddle.inference 桩模块验证 apply() 的平台/CPU 分支逻辑与幂等性，
全程不导入真实 paddle（Windows wheel 无 AVX-512 问题，真实导入会误打补丁），
可离线独立运行。
"""
import sys
import types

from servers.ocr import paddle_compat


def _make_fake_paddle():
    """构造带 switch_ir_optim 的假 Config 与假 paddle 包，返回 (calls, Config, paddle)。"""
    calls: list = []

    class ConfigStub:
        switch_ir_optim = lambda self, flag: calls.append(flag)  # noqa: E731

    paddle_stub = types.SimpleNamespace()
    paddle_stub.inference = types.SimpleNamespace(Config=ConfigStub)
    return calls, ConfigStub, paddle_stub


def _inject_fake_paddle(monkeypatch, paddle_stub) -> None:
    """把假 paddle 注册进 sys.modules，让 apply() 的 import 落到桩上。"""
    monkeypatch.setitem(sys.modules, "paddle", paddle_stub)
    monkeypatch.setitem(sys.modules, "paddle.inference", paddle_stub.inference)


def test_apply_skips_on_non_linux(monkeypatch):
    """非 Linux 平台：apply() 直接 no-op，不打补丁。"""
    calls, config_cls, paddle_stub = _make_fake_paddle()
    _inject_fake_paddle(monkeypatch, paddle_stub)
    monkeypatch.setattr(sys, "platform", "win32")

    paddle_compat.apply()

    config_cls().switch_ir_optim(True)
    assert calls == [True], "非 Linux 不应改动 switch_ir_optim 行为"


def test_apply_keeps_ir_optim_when_avx512(monkeypatch):
    """Linux 但 CPU 支持 AVX-512：保持 IR 优化开启，不打补丁。"""
    calls, config_cls, paddle_stub = _make_fake_paddle()
    _inject_fake_paddle(monkeypatch, paddle_stub)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paddle_compat, "_has_avx512", lambda: True)

    paddle_compat.apply()

    config_cls().switch_ir_optim(True)
    assert calls == [True], "有 AVX-512 的 CPU 不应禁用 IR 优化"


def test_apply_forces_ir_optim_off_without_avx512(monkeypatch):
    """Linux 且 CPU 无 AVX-512：switch_ir_optim 被包装为强制 False。"""
    calls, config_cls, paddle_stub = _make_fake_paddle()
    _inject_fake_paddle(monkeypatch, paddle_stub)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paddle_compat, "_has_avx512", lambda: False)

    paddle_compat.apply()

    config_cls().switch_ir_optim(True)
    assert calls == [False], "无 AVX-512 的 CPU 上应强制关闭 IR 优化"


def test_apply_idempotent_without_avx512(monkeypatch):
    """无 AVX-512 时重复调用 apply() 不重复包装，行为仍是强制 False。"""
    calls, config_cls, paddle_stub = _make_fake_paddle()
    _inject_fake_paddle(monkeypatch, paddle_stub)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paddle_compat, "_has_avx512", lambda: False)

    paddle_compat.apply()
    paddle_compat.apply()

    config_cls().switch_ir_optim(True)
    assert calls == [False], "重复 apply() 不应二次包装 switch_ir_optim"
