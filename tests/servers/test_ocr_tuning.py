"""OCR 构造参数透传单元测试（config.OCR_CPU_THREADS / OCR_DEVICE 配置化生效）。

通过注入假 paddleocr 模块到 sys.modules，让 _load_paddleocr 走真实构造路径，
并记录假类实例收到的 cpu_threads/device，验证 core.py 读取的是运行时 config
而非硬编码。全程离线、不加载真实 PaddleOCR。
"""
import sys
import types
from contextlib import contextmanager
from typing import Iterator

import pytest
from unittest.mock import patch

import servers.ocr.core as ocr_module
from backend.core import config


@contextmanager
def _inject_fake_paddleocr() -> Iterator[type]:
    """把假 paddleocr 模块注入 sys.modules，返回记录构造参数的假 PaddleOCR 类。

    退出时恢复原模块，保证不影响其它用例。
    """
    fake_module = types.ModuleType("paddleocr")

    class _FakePaddleOCR:
        def __init__(self, show_log: bool = False, use_angle_cls: bool = True,
                     lang: str = "ch", cpu_threads: object = None,
                     device: str = "cpu") -> None:
            self.lang = lang
            self.cpu_threads = cpu_threads
            self.device = device

        def ocr(self, path: str, cls: bool = True) -> list:
            return [[[None, ("文本", 0.9)]]]

    fake_module.PaddleOCR = _FakePaddleOCR
    original = sys.modules.get("paddleocr")
    sys.modules["paddleocr"] = fake_module
    try:
        yield _FakePaddleOCR
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


def test_load_paddleocr_passes_config_defaults_to_constructor():
    """默认配置下构造收到 cpu_threads=2、device='cpu'（读 config 模块属性）。"""
    with _inject_fake_paddleocr():
        ocr_module._load_paddleocr("ch")
        instance = ocr_module._ocr_instances["ch"]
    assert instance.cpu_threads == 2
    assert instance.device == "cpu"


def test_load_paddleocr_honors_runtime_config_override():
    """patch config 模块属性后构造收到对应值，验证配置化生效而非硬编码。"""
    with patch.object(config, "OCR_CPU_THREADS", 4), \
            patch.object(config, "OCR_DEVICE", "gpu"):
        with _inject_fake_paddleocr():
            ocr_module._load_paddleocr("ch")
            instance = ocr_module._ocr_instances["ch"]
    assert instance.cpu_threads == 4
    assert instance.device == "gpu"
