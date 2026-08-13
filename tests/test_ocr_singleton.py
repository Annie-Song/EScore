"""OCR 模块级单例缓存单元测试。

通过注入假 paddleocr 模块到 sys.modules，验证 _load_paddleocr 的真实缓存路径，
全程离线、不加载真实 PaddleOCR。
"""
import sys
import threading
import types
from contextlib import contextmanager
from typing import Dict, Iterator, Tuple

import pytest

import services.ocr as ocr_module
from services.ocr import recognize_texts


@contextmanager
def _inject_fake_paddleocr(*, raise_on_init: bool = False) -> Iterator[Tuple[Dict[str, int], type]]:
    """把假 paddleocr 模块注入 sys.modules，返回 (构造计数器, 假 PaddleOCR 类)。

    退出时恢复原模块，保证不影响其它用例。
    """
    fake_module = types.ModuleType("paddleocr")
    counter: Dict[str, int] = {"count": 0}

    class _FakePaddleOCR:
        def __init__(self, show_log: bool = False, use_angle_cls: bool = True, lang: str = "ch") -> None:
            counter["count"] += 1
            if raise_on_init:
                raise RuntimeError("mock paddleocr init failure")
            self.lang = lang
            self.calls: list = []

        def ocr(self, path: str, cls: bool = True) -> list:
            self.calls.append(path)
            return [[[None, (f"文本-{path}", 0.9)]]]

    fake_module.PaddleOCR = _FakePaddleOCR
    original = sys.modules.get("paddleocr")
    sys.modules["paddleocr"] = fake_module
    try:
        yield counter, _FakePaddleOCR
    finally:
        if original is not None:
            sys.modules["paddleocr"] = original
        else:
            sys.modules.pop("paddleocr", None)


@pytest.fixture(autouse=True)
def _reset_ocr_singleton_cache():
    """每轮测试前后复位模块级缓存，隔离用例间状态。"""
    ocr_module._ocr_instances.clear()
    yield
    ocr_module._ocr_instances.clear()


def test_load_paddleocr_same_lang_returns_same_instance():
    """同 lang 连续加载返回同一单例，PaddleOCR 仅构造一次。"""
    with _inject_fake_paddleocr() as (counter, _):
        first = ocr_module._load_paddleocr("ch")
        second = ocr_module._load_paddleocr("ch")
    assert first is second
    assert counter["count"] == 1


def test_load_paddleocr_different_lang_creates_independent_instances():
    """不同 lang 返回不同实例，各自构造一次。"""
    with _inject_fake_paddleocr() as (counter, _):
        ch = ocr_module._load_paddleocr("ch")
        en = ocr_module._load_paddleocr("en")
    assert ch is not en
    assert counter["count"] == 2


def test_recognize_texts_reuses_cached_ocr_instance():
    """recognize_texts 连续调用复用缓存实例，底层 PaddleOCR 仅构造一次。"""
    with _inject_fake_paddleocr() as (counter, _):
        first = recognize_texts(["a.jpg"], lang="ch")
        second = recognize_texts(["b.jpg"], lang="ch")
    assert first == ["文本-a.jpg"]
    assert second == ["文本-b.jpg"]
    assert counter["count"] == 1


def test_load_paddleocr_concurrent_calls_construct_only_once():
    """多线程并发加载同 lang，double-checked locking 保证 PaddleOCR 仅构造一次。"""
    with _inject_fake_paddleocr() as (counter, _):
        threads = []
        instances = []
        errors = []

        def _call() -> None:
            try:
                instances.append(ocr_module._load_paddleocr("ch"))
            except Exception as exc:  # noqa: BLE001 - 测试内收集异常便于断言
                errors.append(exc)

        for _ in range(8):
            thread = threading.Thread(target=_call)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()

    assert errors == []
    assert counter["count"] == 1
    assert len({id(instance) for instance in instances}) == 1


def test_load_paddleocr_init_error_does_not_pollute_cache():
    """构造异常时异常向上抛出且缓存不含该 lang；修好后可成功创建。"""
    with _inject_fake_paddleocr(raise_on_init=True) as (_, _fake_cls):
        with pytest.raises(RuntimeError, match="mock paddleocr init failure"):
            ocr_module._load_paddleocr("ch")
        assert "ch" not in ocr_module._ocr_instances

    with _inject_fake_paddleocr() as (counter, _):
        instance = ocr_module._load_paddleocr("ch")
        assert instance is ocr_module._ocr_instances["ch"]
        assert counter["count"] == 1
