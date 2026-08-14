"""向量嵌入 HTTP 客户端单元测试：encode / semantic_similarity / _post fail-fast。

旧版面向进程内模型与参考缓存（_get_model/_REF_CACHE），A8 拆分后客户端改为
纯 HTTP 调用，此处按新契约重写。测试全部离线运行，不发起真实 HTTP。
"""
from typing import Optional
from unittest.mock import Mock, patch

import httpx
import numpy as np
import pytest

from services.embedding import _BASE, _post, encode, semantic_similarity


class _FakeClient:
    """记录 post 调用的假 httpx.Client，可配置成功响应或抛出网络错误。"""

    def __init__(self, response: Optional[Mock] = None, error: Optional[Exception] = None):
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict) -> Mock:
        """模拟 httpx.Client.post：记录调用，按配置返回响应或抛网络错误。"""
        self.calls.append((url, json))
        if self.error is not None:
            raise self.error
        return self.response


def _make_response(status_code: int = 200, data: Optional[dict] = None, bad_json: bool = False) -> Mock:
    """构造假响应对象：status_code + .json()，bad_json=True 时 json() 抛 ValueError。"""
    resp = Mock()
    resp.status_code = status_code
    if bad_json:
        resp.json.side_effect = ValueError("invalid json")
    else:
        resp.json.return_value = data
    return resp


def test_encode_parses_vectors_to_float32_ndarray():
    """encode 将服务端 vectors 解析为 float32 ndarray，dtype/shape/值正确。"""
    with patch("services.embedding._post", return_value={"vectors": [[0.5, 0.5], [0.2, 0.8]]}):
        result = encode(["甲", "乙"])
    assert result.dtype == np.float32
    assert result.shape == (2, 2)
    np.testing.assert_array_equal(result, np.array([[0.5, 0.5], [0.2, 0.8]], dtype=np.float32))


def test_encode_missing_vectors_raises_runtime_error():
    """响应缺 vectors 字段时抛 RuntimeError，消息含字段名与端点。"""
    with patch("services.embedding._post", return_value={}):
        with pytest.raises(RuntimeError, match="'vectors'"):
            encode(["甲"])


def test_semantic_similarity_parses_score():
    """semantic_similarity 解析服务端 score 返回 float；整型 score 也转 float。"""
    with patch("services.embedding._post", return_value={"score": 0.75}):
        assert semantic_similarity("参考", "答案") == 0.75
    with patch("services.embedding._post", return_value={"score": 1}):
        assert semantic_similarity("参考", "答案") == 1.0


def test_semantic_similarity_missing_score_raises_runtime_error():
    """响应缺 score 字段时抛 RuntimeError，消息含字段名。"""
    with patch("services.embedding._post", return_value={}):
        with pytest.raises(RuntimeError, match="'score'"):
            semantic_similarity("参考", "答案")


def test_post_network_error_raises_runtime_error_with_url_and_hint():
    """_post 网络错误（httpx.HTTPError 子类）→ RuntimeError，消息含 URL 与启动指引。"""
    client = _FakeClient(error=httpx.ConnectError("connection refused"))
    with patch("services.embedding._get_client", return_value=client):
        with pytest.raises(RuntimeError) as exc_info:
            _post("/encode", {"texts": ["甲"]})
    assert f"{_BASE}/encode" in str(exc_info.value)
    assert "请先启动 python -m services.embedding_server" in str(exc_info.value)
    assert client.calls == [(f"{_BASE}/encode", {"texts": ["甲"]})]


def test_encode_network_error_raises_runtime_error_with_hint():
    """encode 全链路：网络超时 → RuntimeError，消息含启动指引，不静默降级。"""
    client = _FakeClient(error=httpx.TimeoutException("timed out"))
    with patch("services.embedding._get_client", return_value=client):
        with pytest.raises(RuntimeError, match="请先启动 python -m services.embedding_server"):
            encode(["甲"])


def test_encode_non_2xx_status_raises_runtime_error_with_status_code():
    """encode 全链路：服务端 500 → RuntimeError，消息含状态码与启动指引。"""
    client = _FakeClient(response=_make_response(status_code=500, data={"detail": "boom"}))
    with patch("services.embedding._get_client", return_value=client):
        with pytest.raises(RuntimeError) as exc_info:
            encode(["甲"])
    assert "500" in str(exc_info.value)
    assert "请先启动 python -m services.embedding_server" in str(exc_info.value)


def test_encode_json_parse_failure_raises_runtime_error():
    """encode 全链路：服务端返回非法 JSON → RuntimeError，消息含解析失败与 URL。"""
    client = _FakeClient(response=_make_response(status_code=200, bad_json=True))
    with patch("services.embedding._get_client", return_value=client):
        with pytest.raises(RuntimeError) as exc_info:
            encode(["甲"])
    assert "JSON 解析失败" in str(exc_info.value)
    assert f"{_BASE}/encode" in str(exc_info.value)


def test_encode_posts_correct_path_and_payload():
    """encode 请求路径为 /encode，JSON body 为 {"texts": [...]}。"""
    client = _FakeClient(response=_make_response(data={"vectors": [[1.0]]}))
    with patch("services.embedding._get_client", return_value=client):
        encode(["甲", "乙"])
    assert client.calls == [(f"{_BASE}/encode", {"texts": ["甲", "乙"]})]


def test_semantic_similarity_posts_correct_path_and_payload():
    """semantic_similarity 请求路径为 /similarity，JSON body 含 reference/answer。"""
    client = _FakeClient(response=_make_response(data={"score": 0.5}))
    with patch("services.embedding._get_client", return_value=client):
        semantic_similarity("参考", "答案")
    assert client.calls == [(f"{_BASE}/similarity", {"reference": "参考", "answer": "答案"})]


def test_offline_score_still_maps_mocked_semantic_similarity():
    """调用方回归：services.scoring.offline_score 经 mock semantic_similarity 仍正常映射百分制。"""
    from services.scoring import offline_score

    with patch("services.scoring.semantic_similarity", return_value=0.75) as mock_sim:
        assert offline_score("参考", "答案") == 75.0
    mock_sim.assert_called_once_with("参考", "答案")
