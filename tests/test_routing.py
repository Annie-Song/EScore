"""级联精排路由判断单元测试。"""
from unittest.mock import patch

from services.scoring import should_route


def test_should_route_threshold_below_threshold_routes():
    with patch("services.scoring.ROUTING_MODE", "threshold"):
        assert should_route(59.9) is True


def test_should_route_threshold_at_threshold_does_not_route():
    with patch("services.scoring.ROUTING_MODE", "threshold"):
        assert should_route(60.0) is False


def test_should_route_threshold_above_threshold_does_not_route():
    with patch("services.scoring.ROUTING_MODE", "threshold"):
        assert should_route(90.0) is False


def test_should_route_band_lower_boundary_routes():
    with patch("services.scoring.ROUTING_MODE", "band"):
        assert should_route(40.0) is True


def test_should_route_band_upper_boundary_routes():
    with patch("services.scoring.ROUTING_MODE", "band"):
        assert should_route(80.0) is True


def test_should_route_band_within_band_routes():
    with patch("services.scoring.ROUTING_MODE", "band"):
        assert should_route(50.0) is True


def test_should_route_band_below_lower_boundary_does_not_route():
    with patch("services.scoring.ROUTING_MODE", "band"):
        assert should_route(39.9) is False


def test_should_route_band_above_upper_boundary_does_not_route():
    with patch("services.scoring.ROUTING_MODE", "band"):
        assert should_route(80.1) is False


def test_should_route_off_never_routes():
    with patch("services.scoring.ROUTING_MODE", "off"):
        assert should_route(0.0) is False
        assert should_route(50.0) is False
        assert should_route(100.0) is False


def test_should_route_unknown_mode_never_routes():
    with patch("services.scoring.ROUTING_MODE", "unknown"):
        assert should_route(0.0) is False
        assert should_route(50.0) is False
        assert should_route(100.0) is False
