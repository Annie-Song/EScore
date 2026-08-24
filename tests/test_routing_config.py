"""级联精排路由双档预设（RoutingConfig / resolve_preset / should_route）单元测试。"""
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from backend.scoring.engine import RoutingConfig, resolve_preset, should_route


def test_routing_config_frozen_dataclass_has_preset_defaults():
    """RoutingConfig 默认值与模块级常量一致：threshold/60/40/80。"""
    cfg = RoutingConfig()
    assert cfg.mode == "threshold"
    assert cfg.low == 60.0
    assert cfg.band_low == 40.0
    assert cfg.band_high == 80.0


def test_routing_config_frozen_prevents_mutation():
    """frozen dataclass 字段不可变。"""
    cfg = RoutingConfig()
    with pytest.raises(FrozenInstanceError):
        cfg.low = 1


def test_resolve_preset_fast_uses_low_60():
    """fast 预设解析为 threshold 低分路由，low=60。"""
    cfg = resolve_preset("fast")
    assert cfg.mode == "threshold"
    assert cfg.low == 60.0


def test_resolve_preset_quality_uses_low_80():
    """quality 预设解析为 threshold 低分路由，low=80。"""
    cfg = resolve_preset("quality")
    assert cfg.mode == "threshold"
    assert cfg.low == 80.0


def test_resolve_preset_unknown_raises_value_error_with_options():
    """未知名抛 ValueError 且 message 含可选预设名。"""
    with pytest.raises(ValueError) as exc:
        resolve_preset("ultra")
    message = str(exc.value)
    assert "fast" in message
    assert "quality" in message


def test_should_route_explicit_threshold_below_low_routes():
    """显式 RoutingConfig：threshold 模式下低于 low 路由。"""
    routing = RoutingConfig(mode="threshold", low=60.0)
    assert should_route(59.9, routing) is True


def test_should_route_explicit_threshold_at_low_not_route():
    """显式 RoutingConfig：threshold 模式下达到/超过 low 不路由。"""
    routing = RoutingConfig(mode="threshold", low=60.0)
    assert should_route(60.0, routing) is False
    assert should_route(90.0, routing) is False


def test_should_route_explicit_band_within_routes():
    """显式 RoutingConfig：band 模式在 [band_low, band_high] 内路由（含边界）。"""
    routing = RoutingConfig(mode="band", band_low=40.0, band_high=80.0)
    assert should_route(40.0, routing) is True
    assert should_route(80.0, routing) is True
    assert should_route(50.0, routing) is True


def test_should_route_explicit_band_outside_not_route():
    """显式 RoutingConfig：band 模式越界不路由。"""
    routing = RoutingConfig(mode="band", band_low=40.0, band_high=80.0)
    assert should_route(39.9, routing) is False
    assert should_route(80.1, routing) is False


def test_should_route_explicit_off_never_routes():
    """显式 RoutingConfig：mode='off' 一律不路由。"""
    routing = RoutingConfig(mode="off")
    assert should_route(0.0, routing) is False
    assert should_route(100.0, routing) is False


def test_should_route_explicit_unknown_mode_never_routes():
    """显式 RoutingConfig：未知 mode 一律不路由。"""
    routing = RoutingConfig(mode="weird")
    assert should_route(50.0, routing) is False


def test_should_route_default_reads_module_threshold_constants():
    """缺省 routing 读模块级常量（回归：patch ROUTING_MODE/LOW_THRESHOLD 后按 patch 值决策）。"""
    with patch("backend.scoring.engine.ROUTING_MODE", "threshold"), \
         patch("backend.scoring.engine.LOW_THRESHOLD", 70.0):
        # 65 < 70（patch 值）应路由；若误用类默认值 60.0 则 65 >= 60 不路由
        assert should_route(65.0) is True
        assert should_route(70.0) is False


def test_should_route_default_reads_module_band_constants():
    """缺省 routing 读模块级 BAND_* 常量。"""
    with patch("backend.scoring.engine.ROUTING_MODE", "band"), \
         patch("backend.scoring.engine.BAND_LOW", 30.0), \
         patch("backend.scoring.engine.BAND_HIGH", 90.0):
        assert should_route(50.0) is True
        assert should_route(29.9) is False
        assert should_route(90.1) is False


def test_should_route_resolved_fast_preset():
    """resolve_preset('fast') 与 should_route 集成：low=60 决策。"""
    assert should_route(59.9, resolve_preset("fast")) is True
    assert should_route(60.0, resolve_preset("fast")) is False


def test_should_route_resolved_quality_preset():
    """resolve_preset('quality') 与 should_route 集成：low=80 决策。"""
    assert should_route(79.9, resolve_preset("quality")) is True
    assert should_route(80.0, resolve_preset("quality")) is False
