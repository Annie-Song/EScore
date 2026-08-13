"""评分模块单元测试。"""
from unittest.mock import patch

from services.scoring import offline_score, online_score, grade_answer


def test_offline_score_identical_texts_return_full():
    assert offline_score("水的沸点是100℃", "水的沸点是100℃") == 100.0


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


def test_grade_answer_offline_mode_uses_offline_score():
    result = grade_answer("参考", "答案", False)
    assert result["method"] == "offline"
    assert result["degraded"] is False


def test_grade_answer_online_mode_returns_online_result():
    with patch("services.scoring.get_points", return_value=1.0):
        result = grade_answer("参考", "答案", True)
        assert result == {"score": 100.0, "method": "online", "degraded": False}


def test_grade_answer_online_failure_falls_back_to_offline():
    with patch("services.scoring.get_points", return_value=None):
        result = grade_answer("水的沸点是100℃", "水的沸点是100℃", True)
        assert result["method"] == "offline"
        assert result["degraded"] is True
        assert result["score"] == 100.0
