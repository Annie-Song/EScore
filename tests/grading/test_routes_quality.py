"""/compare_texts 路由 quality 双档贯通单元测试（外部依赖 grade_answer 全 mock）。"""
import pytest
from unittest.mock import patch

from backend.app import create_app


@pytest.fixture
def client():
    """构造 Flask 测试客户端。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _payload(**overrides):
    """构造合法请求体，quality/forceOnline 由 overrides 覆盖。"""
    payload = {
        "workContent": "小明解方程 2x+3=7 得 x=2",
        "answerContent": "2x+3=7 移项得 2x=4，解得 x=2",
    }
    payload.update(overrides)
    return payload


def _full_result(score: float = 88.5, method: str = "online",
                 degraded: bool = False, routed: bool = True) -> dict:
    """构造 grade_answer 的完整返回结构。"""
    return {"score": score, "method": method, "degraded": degraded, "routed": routed}


def test_compare_texts_default_no_quality_passes_fast(client):
    """缺省无 quality 字段 → grade_answer 收到 quality_mode='fast'。"""
    with patch("backend.grading.routes.grade_answer", return_value=_full_result()) as mock_grade:
        resp = client.post("/compare_texts", json=_payload())
    assert resp.status_code == 200
    mock_grade.assert_called_once()
    assert mock_grade.call_args.kwargs["quality_mode"] == "fast"


def test_compare_texts_quality_quality_passes_quality(client):
    """quality='quality' → grade_answer 收到 quality_mode='quality'。"""
    with patch("backend.grading.routes.grade_answer", return_value=_full_result()) as mock_grade:
        resp = client.post("/compare_texts", json=_payload(quality="quality"))
    assert resp.status_code == 200
    mock_grade.assert_called_once()
    assert mock_grade.call_args.kwargs["quality_mode"] == "quality"


def test_compare_texts_empty_quality_falls_back_to_fast(client):
    """quality='' 空串回退默认 fast（与 /batch_grade 行为一致），不报 400。"""
    with patch("backend.grading.routes.grade_answer", return_value=_full_result()) as mock_grade:
        resp = client.post("/compare_texts", json=_payload(quality=""))
    assert resp.status_code == 200
    mock_grade.assert_called_once()
    assert mock_grade.call_args.kwargs["quality_mode"] == "fast"


def test_compare_texts_invalid_quality_returns_400(client):
    """quality='garbage' → 400 且 message 含未知评分质量，grade_answer 不被调用。"""
    with patch("backend.grading.routes.grade_answer") as mock_grade:
        resp = client.post("/compare_texts", json=_payload(quality="garbage"))
    assert resp.status_code == 400
    message = resp.get_json()["message"]
    assert "未知评分质量" in message
    assert "garbage" in message
    mock_grade.assert_not_called()


def test_compare_texts_result_structure_preserved(client):
    """返回结构 score/method/degraded/routed 不被 quality 破坏。"""
    result = _full_result(score=90.0, method="online", degraded=False, routed=True)
    with patch("backend.grading.routes.grade_answer", return_value=result):
        resp = client.post("/compare_texts", json=_payload(quality="quality"))
    assert resp.status_code == 200
    assert resp.get_json() == result


def test_compare_texts_force_online_and_quality_both_passed(client):
    """forceOnline=True 与 quality='quality' 同时透传给 grade_answer。"""
    with patch("backend.grading.routes.grade_answer", return_value=_full_result()) as mock_grade:
        resp = client.post(
            "/compare_texts", json=_payload(forceOnline=True, quality="quality")
        )
    assert resp.status_code == 200
    mock_grade.assert_called_once()
    assert mock_grade.call_args.kwargs["force_online"] is True
    assert mock_grade.call_args.kwargs["quality_mode"] == "quality"
