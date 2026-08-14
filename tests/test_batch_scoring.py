"""批量评分模块单元测试：批量离线评分与级联精排。"""
from unittest.mock import patch

import pytest

from services.batch_scoring import batch_offline_scores, grade_batch


def test_batch_offline_scores_maps_similarity_to_percent_clamped_rounded():
    """0-1 相似度映射百分制，越界 clamp，结果保留 1 位小数。"""
    sims = [0.5, 1.0, 0.0, 1.5, -0.25, 0.1234]
    with patch("services.batch_scoring.batch_similarities", return_value=sims) as mock_sim:
        scores = batch_offline_scores("参考", ["答"] * len(sims))
    assert scores == [50.0, 100.0, 0.0, 100.0, 0.0, 12.3]
    mock_sim.assert_called_once_with("参考", ["答"] * len(sims))


def test_batch_offline_scores_empty_answers_returns_empty():
    """answers 为空返回空列表，不调用 batch_similarities。"""
    with patch("services.batch_scoring.batch_similarities") as mock_sim:
        assert batch_offline_scores("参考", []) == []
    mock_sim.assert_not_called()


def test_grade_batch_force_online_all_success():
    """force_online 全在线成功：全 online、无 routed、无 degraded。"""
    with patch("services.batch_scoring.online_score", side_effect=[80.0, 90.0, 70.0]) as mock_online, \
         patch("services.batch_scoring.offline_score") as mock_offline:
        results = grade_batch("参考", ["a", "b", "c"], force_online=True)
    assert results == [
        {"score": 80.0, "method": "online", "degraded": False, "routed": False},
        {"score": 90.0, "method": "online", "degraded": False, "routed": False},
        {"score": 70.0, "method": "online", "degraded": False, "routed": False},
    ]
    assert mock_online.call_count == 3
    mock_offline.assert_not_called()


def test_grade_batch_force_online_partial_failure_degrades():
    """force_online 部分在线失败降级离线并标记 degraded。"""
    with patch("services.batch_scoring.online_score", side_effect=[80.0, None, None]), \
         patch("services.batch_scoring.offline_score", side_effect=[55.0, 60.0]):
        results = grade_batch("参考", ["a", "b", "c"], force_online=True)
    assert results == [
        {"score": 80.0, "method": "online", "degraded": False, "routed": False},
        {"score": 55.0, "method": "offline", "degraded": True, "routed": False},
        {"score": 60.0, "method": "offline", "degraded": True, "routed": False},
    ]


def test_grade_batch_auto_no_route_returns_offline():
    """should_route=False：全部返回离线结果，不触发在线评分。"""
    with patch("services.batch_scoring.batch_offline_scores", return_value=[50.0, 60.0]), \
         patch("services.batch_scoring.should_route", return_value=False) as mock_route, \
         patch("services.batch_scoring.online_score") as mock_online:
        results = grade_batch("参考", ["a", "b"], force_online=False)
    assert results == [
        {"score": 50.0, "method": "offline", "degraded": False, "routed": False},
        {"score": 60.0, "method": "offline", "degraded": False, "routed": False},
    ]
    assert mock_route.call_count == 2
    mock_online.assert_not_called()


def test_grade_batch_auto_route_success_returns_online():
    """should_route=True 且在线成功：online 结果 routed=True。"""
    with patch("services.batch_scoring.batch_offline_scores", return_value=[40.0]), \
         patch("services.batch_scoring.should_route", return_value=True), \
         patch("services.batch_scoring.online_score", return_value=90.0):
        results = grade_batch("参考", ["a"], force_online=False)
    assert results == [{"score": 90.0, "method": "online", "degraded": False, "routed": True}]


def test_grade_batch_auto_route_failure_degrades_to_offline():
    """should_route=True 且在线失败：降级离线 degraded=True、routed=True。"""
    with patch("services.batch_scoring.batch_offline_scores", return_value=[40.0]), \
         patch("services.batch_scoring.should_route", return_value=True), \
         patch("services.batch_scoring.online_score", return_value=None):
        results = grade_batch("参考", ["a"], force_online=False)
    assert results == [{"score": 40.0, "method": "offline", "degraded": True, "routed": True}]


def test_grade_batch_results_length_matches_answers():
    """返回结果列表与 answers 一一对应。"""
    with patch("services.batch_scoring.batch_offline_scores", return_value=[10.0, 20.0, 30.0]), \
         patch("services.batch_scoring.should_route", return_value=True), \
         patch("services.batch_scoring.online_score", return_value=99.0):
        results = grade_batch("参考", ["a", "b", "c"], force_online=False)
    assert len(results) == 3


def test_grade_batch_quality_mode_fast_keeps_75_offline():
    """批量 offline=75：fast 预设（low=60）不路由，真实 should_route 逻辑返回离线结果。"""
    with patch("services.batch_scoring.batch_offline_scores", return_value=[75.0]), \
         patch("services.batch_scoring.online_score", return_value=90.0):
        results = grade_batch("参考", ["a"], force_online=False, quality_mode="fast")
    assert results == [{"score": 75.0, "method": "offline", "degraded": False, "routed": False}]


def test_grade_batch_quality_mode_quality_routes_75_to_online():
    """批量 offline=75：quality 预设（low=80）路由到在线精排，返回在线结果。"""
    with patch("services.batch_scoring.batch_offline_scores", return_value=[75.0]), \
         patch("services.batch_scoring.online_score", return_value=90.0):
        results = grade_batch("参考", ["a"], force_online=False, quality_mode="quality")
    assert results == [{"score": 90.0, "method": "online", "degraded": False, "routed": True}]


def test_grade_batch_unknown_quality_mode_raises_even_force_online():
    """未知 quality_mode 抛 ValueError，force_online=True 也抛（fail-fast 开头 resolve_preset）。"""
    with patch("services.batch_scoring.online_score", return_value=90.0), \
         patch("services.batch_scoring.offline_score", return_value=50.0):
        with pytest.raises(ValueError, match="未知路由预设"):
            grade_batch("参考", ["a"], force_online=True, quality_mode="ultra")
