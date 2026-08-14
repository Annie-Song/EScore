"""批量向量嵌入 HTTP 客户端单元测试：encode_reference / batch_similarities。

旧版面向进程内参考缓存（_REF_CACHE），A8 拆分后客户端改为纯 HTTP 调用，
此处按新契约重写。测试全部离线运行，不发起真实 HTTP。
"""
from typing import Optional
from unittest.mock import Mock, patch

import httpx
import numpy as np
import pytest

from services.embedding import _BASE, batch_similarities, encode_reference


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


def test_encode_reference_parses_vector():
    """encode_reference 解析服务端 vector 为 float32 ndarray。"""
    with patch("services.embedding._post", return_value={"vector": [0.3, 0.7]}):
        result = encode_reference("参考")
    assert result.dtype == np.float32
    np.testing.assert_array_equal(result, np.array([0.3, 0.7], dtype=np.float32))


def test_encode_reference_empty_text_short_circuits_without_http():
    """空参考文本本地短路：返回 np.empty(0, float32) 且不发起 HTTP。"""
    with patch("services.embedding._post") as mock_post:
        result = encode_reference("")
    assert isinstance(result, np.ndarray)
    assert result.size == 0
    assert result.dtype == np.float32
    mock_post.assert_not_called()


def test_encode_reference_missing_vector_raises_runtime_error():
    """响应缺 vector 字段时抛 RuntimeError，消息含字段名。"""
    with patch("services.embedding._post", return_value={}):
        with pytest.raises(RuntimeError, match="'vector'"):
            encode_reference("参考")


def test_encode_reference_posts_correct_path_and_payload():
    """encode_reference 请求路径为 /encode_reference，JSON body 为 {"text": ...}。"""
    client = _FakeClient(response=_make_response(data={"vector": [0.1]}))
    with patch("services.embedding._get_client", return_value=client):
        encode_reference("参考")
    assert client.calls == [(f"{_BASE}/encode_reference", {"text": "参考"})]


def test_batch_similarities_parses_scores_equal_length():
    """batch_similarities 解析 scores，返回与 answers 等长的 float 列表。"""
    answers = ["答1", "答2", "答3"]
    with patch("services.embedding._post", return_value={"scores": [0.9, 0.1, 0.5]}):
        result = batch_similarities("参考", answers)
    assert result == [0.9, 0.1, 0.5]
    assert len(result) == len(answers)


def test_batch_similarities_empty_answers_short_circuits_without_http():
    """answers 为空本地短路：返回 [] 且不发起 HTTP。"""
    with patch("services.embedding._post") as mock_post:
        assert batch_similarities("参考", []) == []
    mock_post.assert_not_called()


def test_batch_similarities_missing_scores_raises_runtime_error():
    """响应缺 scores 字段时抛 RuntimeError，消息含字段名。"""
    with patch("services.embedding._post", return_value={}):
        with pytest.raises(RuntimeError, match="'scores'"):
            batch_similarities("参考", ["答"])


def test_batch_similarities_posts_correct_path_and_payload():
    """batch_similarities 请求路径为 /batch_similarity，JSON body 含 reference/answers。"""
    client = _FakeClient(response=_make_response(data={"scores": [0.2]}))
    with patch("services.embedding._get_client", return_value=client):
        batch_similarities("参考", ["答"])
    assert client.calls == [(f"{_BASE}/batch_similarity", {"reference": "参考", "answers": ["答"]})]


def test_batch_similarities_network_error_raises_runtime_error_with_hint():
    """batch_similarities 全链路：网络错误 → RuntimeError，消息含启动指引。"""
    client = _FakeClient(error=httpx.TimeoutException("timed out"))
    with patch("services.embedding._get_client", return_value=client):
        with pytest.raises(RuntimeError, match="请先启动 python -m services.embedding_server"):
            batch_similarities("参考", ["答"])


def test_batch_offline_scores_still_maps_mocked_batch_similarities():
    """调用方回归：batch_offline_scores 经 mock batch_similarities 仍正常映射百分制。"""
    from services.batch_scoring import batch_offline_scores

    sims = [0.5, 1.0, 0.0, 1.5, -0.25, 0.1234]
    with patch("services.batch_scoring.batch_similarities", return_value=sims) as mock_sim:
        scores = batch_offline_scores("参考", ["答"] * len(sims))
    assert scores == [50.0, 100.0, 0.0, 100.0, 0.0, 12.3]
    mock_sim.assert_called_once_with("参考", ["答"] * len(sims))
