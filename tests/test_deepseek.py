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
    with patch.object(deepseek, "_get_client", return_value=_make_client("0.85")):
        assert deepseek.get_points("ref", "ans") == 0.85


def test_get_points_extracts_decimal_from_text():
    with patch.object(deepseek, "_get_client", return_value=_make_client("我认为应给 0.90 分")):
        assert deepseek.get_points("ref", "ans") == 0.9


def test_get_points_returns_none_on_unparseable_output():
    with patch.object(deepseek, "_get_client", return_value=_make_client("无法评分")):
        assert deepseek.get_points("ref", "ans") is None


def test_get_points_returns_none_on_api_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception("network down")
    with patch.object(deepseek, "_get_client", return_value=client):
        assert deepseek.get_points("ref", "ans") is None


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
