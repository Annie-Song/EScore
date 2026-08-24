"""DeepSeek 客户端单元测试。"""
import os
from unittest.mock import MagicMock, patch

import pytest

from services import deepseek


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _make_client(content):
    client = MagicMock()
    client.chat.completions.create.return_value = _FakeResponse(content)
    return client


def test_get_points_parses_plain_number():
    """裸数字 0.85 应被 float() 兜底解析为 0.85。"""
    with patch.object(deepseek, "_get_client", return_value=_make_client("0.85")):
        assert deepseek.get_points("ref", "ans") == 0.85


def test_get_points_returns_none_on_text_embedding_number():
    """E6 契约：文本中的数字不再被正则抠出，非 JSON 非裸数字整体应返回 None。"""
    with patch.object(deepseek, "_get_client", return_value=_make_client("我认为应给 0.90 分")):
        assert deepseek.get_points("ref", "ans") is None


def test_get_points_parses_json_score():
    """标准 JSON {"score": 0.85} 应解析出 0.85。"""
    with patch.object(deepseek, "_get_client", return_value=_make_client('{"score": 0.85}')):
        assert deepseek.get_points("ref", "ans") == 0.85


def test_get_points_parses_fenced_json_score():
    """```json 围栏包裹的 JSON 应被剥围栏后成功解析。"""
    content = '```json\n{"score": 0.85}\n```'
    with patch.object(deepseek, "_get_client", return_value=_make_client(content)):
        assert deepseek.get_points("ref", "ans") == 0.85


def test_get_points_clamps_overscore_to_one():
    """越界高分 {"score": 85} 应被钳制到 1.0，杜绝 85×100=8500 旧 bug。"""
    with patch.object(deepseek, "_get_client", return_value=_make_client('{"score": 85}')):
        assert deepseek.get_points("ref", "ans") == 1.0


def test_get_points_clamps_negative_score_to_zero():
    """越界负分 {"score": -0.1} 应被钳制到 0.0。"""
    with patch.object(deepseek, "_get_client", return_value=_make_client('{"score": -0.1}')):
        assert deepseek.get_points("ref", "ans") == 0.0


def test_get_points_returns_none_on_non_numeric_json_score():
    """JSON 的 score 值非数字（如 "abc"）应返回 None，不伪造分数。"""
    with patch.object(deepseek, "_get_client", return_value=_make_client('{"score": "abc"}')):
        assert deepseek.get_points("ref", "ans") is None


def test_get_points_returns_none_on_json_missing_score_key():
    """JSON 缺少 score 键（如 {"foo": 1}）应返回 None。"""
    with patch.object(deepseek, "_get_client", return_value=_make_client('{"foo": 1}')):
        assert deepseek.get_points("ref", "ans") is None


def test_get_points_returns_none_on_unparseable_output():
    """非法文本（无法评分）应返回 None。"""
    with patch.object(deepseek, "_get_client", return_value=_make_client("无法评分")):
        assert deepseek.get_points("ref", "ans") is None


def test_get_points_returns_none_on_api_error():
    """API 抛异常时 get_points 应吞掉异常并返回 None。"""
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception("network down")
    with patch.object(deepseek, "_get_client", return_value=client):
        assert deepseek.get_points("ref", "ans") is None


def test_get_points_sends_json_response_format():
    """E6 契约：get_points 调用 create 时必须传 response_format={"type": "json_object"}。"""
    client = _make_client('{"score": 0.85}')
    with patch.object(deepseek, "_get_client", return_value=client):
        deepseek.get_points("ref", "ans")
    create_call = client.chat.completions.create
    assert create_call.call_args.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    "content, expected",
    [
        ('{"score": 0.85}', 0.85),
        ('{"score": 85}', 1.0),
        ('{"score": -0.1}', 0.0),
        ('{"score": "abc"}', None),
        ('{"foo": 1}', None),
        ("0.85", 0.85),
        ("无法评分", None),
        ('```json\n{"score": 0.85}\n```', 0.85),
        ("", None),
        (None, None),
    ],
)
def test_parse_score_content(content, expected):
    """直接单测 _parse_score_content：JSON/围栏/裸数字/越界钳制/失败返回 None。"""
    assert deepseek._parse_score_content(content) == expected


def test_get_client_raises_without_api_key():
    with patch.dict("os.environ", {}, clear=True):
        with patch.object(deepseek, "_client", None):
            with pytest.raises(RuntimeError):
                deepseek._get_client()


def test_ensure_ssl_cert_clears_nonexistent_cert_file(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "D:/nonexistent/cacert.pem")
    deepseek._ensure_ssl_cert()
    assert "SSL_CERT_FILE" not in os.environ


def test_ensure_ssl_cert_keeps_existing_cert_file(monkeypatch, tmp_path):
    cert = tmp_path / "cacert.pem"
    cert.write_text("dummy")
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    deepseek._ensure_ssl_cert()
    assert os.environ["SSL_CERT_FILE"] == str(cert)


def test_ensure_ssl_cert_noop_without_var(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    deepseek._ensure_ssl_cert()
    assert "SSL_CERT_FILE" not in os.environ
