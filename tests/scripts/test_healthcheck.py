"""scripts/healthcheck 健康检查脚本单元测试（task/26 D3 单环境收敛）。

覆盖 check_endpoints 端点探测与 main 重试逻辑。httpx.Client 全程使用可编程替身
mock，不发真实网络请求；--wait 分支用受控的 monotonic/sleep 驱动重试时序，
保证测试离线、快速、确定性。
"""
from __future__ import annotations

from unittest import mock

import httpx
import pytest

import scripts.healthcheck as healthcheck

ALL_OK = {
    "main": {"ok": True, "status": 200, "elapsed_ms": 1.0},
    "embedding": {"ok": True, "status": 200, "elapsed_ms": 1.0},
    "ocr": {"ok": True, "status": 200, "elapsed_ms": 1.0},
}
ALL_FAIL = {
    name: {**info, "ok": False, "status": None}
    for name, info in ALL_OK.items()
}


def _patch_httpx_client(
    monkeypatch: pytest.MonkeyPatch, behaviors: dict
) -> tuple[mock.Mock, mock.Mock]:
    """用可编程替身替换 healthcheck.httpx.Client。

    behaviors 为 {url: status_code | Exception}：替身按 URL 返回预设状态码或抛出
    预设异常。返回 (client_cls_mock, fake_client)，可断言构造次数与调用次数。
    """
    fake = mock.MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False

    def _get(url: str):
        behavior = behaviors[url]
        if isinstance(behavior, BaseException):
            raise behavior
        resp = mock.Mock()
        resp.status_code = behavior
        return resp

    fake.get.side_effect = _get
    client_cls = mock.Mock(return_value=fake)
    monkeypatch.setattr(healthcheck.httpx, "Client", client_cls)
    return client_cls, fake


class TestCheckEndpoints:
    def test_check_endpoints_all_ok(self, monkeypatch):
        behaviors = {"http://a/health": 200, "http://b/health": 200}
        client_cls, fake = _patch_httpx_client(monkeypatch, behaviors)
        results = healthcheck.check_endpoints(
            [("a", "http://a/health"), ("b", "http://b/health")]
        )
        assert results["a"]["ok"] is True
        assert results["a"]["status"] == 200
        assert isinstance(results["a"]["elapsed_ms"], (int, float))
        assert results["a"]["elapsed_ms"] >= 0
        assert results["b"]["ok"] is True
        assert results["b"]["status"] == 200
        assert client_cls.call_count == 1
        assert fake.get.call_count == 2

    def test_check_endpoints_single_status_fail(self, monkeypatch):
        behaviors = {"http://a/health": 200, "http://b/health": 500}
        _patch_httpx_client(monkeypatch, behaviors)
        results = healthcheck.check_endpoints(
            [("a", "http://a/health"), ("b", "http://b/health")]
        )
        assert results["a"]["ok"] is True
        assert results["a"]["status"] == 200
        assert results["b"]["ok"] is False
        assert results["b"]["status"] == 500
        assert isinstance(results["b"]["elapsed_ms"], (int, float))

    def test_check_endpoints_connect_error_not_interrupt(self, monkeypatch):
        behaviors = {
            "http://a/health": httpx.ConnectError("connection refused"),
            "http://b/health": 200,
        }
        _patch_httpx_client(monkeypatch, behaviors)
        results = healthcheck.check_endpoints(
            [("a", "http://a/health"), ("b", "http://b/health")]
        )
        assert results["a"]["ok"] is False
        assert results["a"]["status"] is None
        assert isinstance(results["a"]["elapsed_ms"], (int, float))
        assert results["b"]["ok"] is True
        assert results["b"]["status"] == 200

    def test_check_endpoints_timeout_error(self, monkeypatch):
        behaviors = {"http://a/health": httpx.ReadTimeout("request timed out")}
        _patch_httpx_client(monkeypatch, behaviors)
        results = healthcheck.check_endpoints([("a", "http://a/health")])
        assert results["a"]["ok"] is False
        assert results["a"]["status"] is None
        assert isinstance(results["a"]["elapsed_ms"], (int, float))

    def test_check_endpoints_timeout_passthrough(self, monkeypatch):
        behaviors = {"http://a/health": 200}
        client_cls, _ = _patch_httpx_client(monkeypatch, behaviors)
        healthcheck.check_endpoints([("a", "http://a/health")], timeout=3.5)
        assert client_cls.call_args.kwargs["timeout"] == 3.5

    def test_check_endpoints_default_timeout(self, monkeypatch):
        behaviors = {"http://a/health": 200}
        client_cls, _ = _patch_httpx_client(monkeypatch, behaviors)
        healthcheck.check_endpoints([("a", "http://a/health")])
        assert client_cls.call_args.kwargs["timeout"] == 2.0

    def test_check_endpoints_reuses_one_client(self, monkeypatch):
        behaviors = {
            "http://a/health": 200,
            "http://b/health": 200,
            "http://c/health": 500,
        }
        client_cls, fake = _patch_httpx_client(monkeypatch, behaviors)
        healthcheck.check_endpoints(
            [
                ("a", "http://a/health"),
                ("b", "http://b/health"),
                ("c", "http://c/health"),
            ]
        )
        assert client_cls.call_count == 1
        assert fake.get.call_count == 3


class TestMain:
    def test_main_all_ok_returns_0(self, monkeypatch):
        monkeypatch.setattr(
            healthcheck, "check_endpoints", mock.Mock(return_value=ALL_OK)
        )
        assert healthcheck.main([]) == 0
        assert healthcheck.check_endpoints.call_count == 1

    def test_main_fail_returns_1(self, monkeypatch):
        monkeypatch.setattr(
            healthcheck, "check_endpoints", mock.Mock(return_value=ALL_FAIL)
        )
        monkeypatch.setattr(healthcheck.time, "monotonic", mock.Mock(return_value=0.0))
        assert healthcheck.main([]) == 1
        assert healthcheck.check_endpoints.call_count == 1

    def test_main_wait_retries_until_ok(self, monkeypatch):
        monkeypatch.setattr(
            healthcheck,
            "check_endpoints",
            mock.Mock(side_effect=[ALL_FAIL, ALL_OK]),
        )
        monkeypatch.setattr(healthcheck.time, "sleep", mock.Mock())
        monkeypatch.setattr(healthcheck.time, "monotonic", mock.Mock(return_value=0.0))
        assert healthcheck.main(["--wait", "5"]) == 0
        assert healthcheck.check_endpoints.call_count == 2
        assert healthcheck.time.sleep.call_count == 1

    def test_main_wait_times_out_returns_1(self, monkeypatch):
        monkeypatch.setattr(
            healthcheck, "check_endpoints", mock.Mock(return_value=ALL_FAIL)
        )
        monkeypatch.setattr(healthcheck.time, "sleep", mock.Mock())
        monkeypatch.setattr(
            healthcheck.time,
            "monotonic",
            mock.Mock(side_effect=[0.0, 0.0, 0.5, 2.0]),
        )
        assert healthcheck.main(["--wait", "1"]) == 1
        assert healthcheck.check_endpoints.call_count == 3
        assert healthcheck.time.sleep.call_count == 2

    def test_main_default_endpoints(self, monkeypatch):
        captured: dict = {}

        def _fake_check(endpoints, timeout=2.0):
            captured["endpoints"] = endpoints
            return ALL_OK

        monkeypatch.setattr(healthcheck, "check_endpoints", _fake_check)
        monkeypatch.setattr(healthcheck, "_MAIN_APP_URL", "http://127.0.0.1:5000")
        monkeypatch.setattr(
            healthcheck.config, "EMBEDDING_SERVICE_URL", "http://127.0.0.1:8765"
        )
        monkeypatch.setattr(healthcheck.config, "OCR_SERVICE_URL", "http://127.0.0.1:8766")
        assert healthcheck.main([]) == 0
        assert captured["endpoints"] == [
            ("main", "http://127.0.0.1:5000/health"),
            ("embedding", "http://127.0.0.1:8765/health"),
            ("ocr", "http://127.0.0.1:8766/health"),
        ]
