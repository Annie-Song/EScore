"""评分模块单元测试。"""
from unittest.mock import patch

import pytest

from services.scoring import offline_score, online_score, grade_answer


def test_offline_score_maps_semantic_similarity_to_percent():
    with patch("services.scoring.semantic_similarity", return_value=0.75):
        assert offline_score("ref", "ans") == 75.0


def test_offline_score_clamps_negative_similarity_to_zero():
    with patch("services.scoring.semantic_similarity", return_value=-0.2):
        assert offline_score("ref", "ans") == 0.0


def test_offline_score_empty_reference_returns_zero():
    assert offline_score("", "任意答案") == 0.0


def test_offline_score_empty_answer_returns_zero():
    assert offline_score("参考答案", "") == 0.0


def test_online_score_scales_deepseek_result_to_percent():
    with patch("services.scoring.get_points", return_value=0.8):
        assert online_score("ref", "ans") == 80.0


def test_online_score_returns_none_when_deepseek_fails():
    with patch("services.scoring.get_points", return_value=None):
        assert online_score("ref", "ans") is None


def test_grade_answer_force_online_success_returns_online_result():
    with patch("services.scoring.get_points", return_value=1.0):
        result = grade_answer("参考", "答案", True)
        assert result == {"score": 100.0, "method": "online", "degraded": False, "routed": False}


def test_grade_answer_force_online_failure_falls_back_to_offline():
    with patch("services.scoring.get_points", return_value=None), \
         patch("services.scoring.semantic_similarity", return_value=1.0):
        result = grade_answer("水的沸点是100℃", "水的沸点是100℃", True)
        assert result == {"score": 100.0, "method": "offline", "degraded": True, "routed": False}


def test_grade_answer_allow_online_false_force_online_true_degrades_offline_no_deepseek():
    """allow_online=False 且 force_online=True：即使离线分低到会触发路由也不调 DeepSeek。

    强制降级离线应返回 method=offline degraded=False，get_points 绝不调用。
    """
    with patch("services.scoring.semantic_similarity", return_value=0.5), \
         patch("services.scoring.get_points") as mock_points:
        result = grade_answer("参考", "答案", True, allow_online=False)
    assert result == {"score": 50.0, "method": "offline", "degraded": False, "routed": False}
    mock_points.assert_not_called()


def test_grade_answer_allow_online_true_force_online_true_uses_online():
    """allow_online=True 且 force_online=True：走在线精排返回 online。"""
    with patch("services.scoring.get_points", return_value=0.8):
        result = grade_answer("参考", "答案", True, allow_online=True)
    assert result == {"score": 80.0, "method": "online", "degraded": False, "routed": False}


def test_grade_answer_allow_online_default_true_matches_explicit():
    """allow_online 缺省为 True，与显式 True 行为一致（回归保障）。"""
    with patch("services.scoring.get_points", return_value=0.8):
        result_default = grade_answer("参考", "答案", True)
    with patch("services.scoring.get_points", return_value=0.8):
        result_explicit = grade_answer("参考", "答案", True, allow_online=True)
    assert result_default == result_explicit == {"score": 80.0, "method": "online",
                                                 "degraded": False, "routed": False}


def test_grade_answer_auto_no_route_uses_offline_result():
    with patch("services.scoring.should_route", return_value=False), \
         patch("services.scoring.semantic_similarity", return_value=0.5):
        result = grade_answer("参考", "答案", False)
        assert result == {"score": 50.0, "method": "offline", "degraded": False, "routed": False}


def test_grade_answer_auto_route_success_returns_online_result():
    with patch("services.scoring.should_route", return_value=True), \
         patch("services.scoring.semantic_similarity", return_value=0.4), \
         patch("services.scoring.get_points", return_value=0.9):
        result = grade_answer("参考", "答案", False)
        assert result == {"score": 90.0, "method": "online", "degraded": False, "routed": True}


def test_grade_answer_auto_route_failure_falls_back_to_offline():
    with patch("services.scoring.should_route", return_value=True), \
         patch("services.scoring.semantic_similarity", return_value=0.4), \
         patch("services.scoring.get_points", return_value=None):
        result = grade_answer("参考", "答案", False)
        assert result == {"score": 40.0, "method": "offline", "degraded": True, "routed": True}


def test_grade_answer_quality_mode_fast_keeps_75_offline():
    """offline=75：fast 预设（low=60）不路由，走真实 should_route 逻辑返回离线结果。"""
    with patch("services.scoring.offline_score", return_value=75.0), \
         patch("services.scoring.get_points", return_value=0.9):
        result = grade_answer("参考", "答案", False, quality_mode="fast")
    assert result == {"score": 75.0, "method": "offline", "degraded": False, "routed": False}


def test_grade_answer_quality_mode_quality_routes_75_to_online():
    """offline=75：quality 预设（low=80）路由到在线精排，返回在线结果。"""
    with patch("services.scoring.offline_score", return_value=75.0), \
         patch("services.scoring.get_points", return_value=0.9):
        result = grade_answer("参考", "答案", False, quality_mode="quality")
    assert result == {"score": 90.0, "method": "online", "degraded": False, "routed": True}


def test_grade_answer_unknown_quality_mode_raises_even_force_online():
    """未知 quality_mode 抛 ValueError，force_online=True 也抛（fail-fast 开头 resolve_preset）。"""
    with patch("services.scoring.get_points", return_value=1.0), \
         patch("services.scoring.offline_score", return_value=50.0):
        with pytest.raises(ValueError, match="未知路由预设"):
            grade_answer("参考", "答案", True, quality_mode="ultra")


def test_grade_answer_default_quality_mode_equals_fast():
    """缺省 quality_mode='fast' 与显式 fast 行为一致（回归保障）。"""
    with patch("services.scoring.should_route", return_value=False), \
         patch("services.scoring.semantic_similarity", return_value=0.5):
        result_default = grade_answer("参考", "答案", False)
    with patch("services.scoring.should_route", return_value=False), \
         patch("services.scoring.semantic_similarity", return_value=0.5):
        result_fast = grade_answer("参考", "答案", False, quality_mode="fast")
    assert result_default == result_fast
