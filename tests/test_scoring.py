"""评分模块单元测试。"""
from unittest.mock import patch

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
