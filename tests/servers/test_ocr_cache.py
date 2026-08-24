"""servers/ocr/core.py recognize_texts 文本缓存单元测试。

覆盖按 (file_sha1(path), lang) 缓存：同一文件重复调用不重复识别、
不同内容/不同 lang 视为不同键、缓存键与路径解耦（内容寻址）。
通过注入假 paddleocr 模块保证离线，并 patch recognize_single 计数，
全程不加载真实 PaddleOCR。
"""
import sys
import types
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch

import pytest

import servers.ocr.core as ocr_module
from servers.ocr.core import recognize_texts


@contextmanager
def _inject_fake_paddleocr() -> Iterator[type]:
    """把假 paddleocr 模块注入 sys.modules，保证离线；退出时恢复原模块。"""
    fake_module = types.ModuleType("paddleocr")

    class _FakePaddleOCR:
        def __init__(self, show_log: bool = False, use_angle_cls: bool = True,
                     lang: str = "ch", cpu_threads: object = None,
                     device: str = "cpu") -> None:
            self.lang = lang
            self.cpu_threads = cpu_threads
            self.device = device

        def ocr(self, path: str, cls: bool = True) -> list:
            return [[[None, (f"文本-{path}", 0.9)]]]

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
def _reset_ocr_cache():
    """每轮测试前后清空模块级文本缓存与 OCR 实例，隔离用例间状态。"""
    ocr_module._text_cache.clear()
    ocr_module._ocr_instances.clear()
    yield
    ocr_module._text_cache.clear()
    ocr_module._ocr_instances.clear()


def test_recognize_texts_same_file_calls_recognize_single_once(tmp_path):
    """同一文件连续两次调用，第二次命中缓存，recognize_single 只执行一次。"""
    path = tmp_path / "same.png"
    path.write_bytes(b"image-content-1")
    with _inject_fake_paddleocr(), \
            patch("servers.ocr.core.recognize_single", return_value="作业文本") as mock_single:
        first = recognize_texts([str(path)], lang="ch")
        second = recognize_texts([str(path)], lang="ch")
    assert first == ["作业文本"]
    assert second == ["作业文本"]
    assert mock_single.call_count == 1


def test_recognize_texts_different_files_each_computed_once(tmp_path):
    """不同内容文件各自识别一次，recognize_single 调用两次。"""
    path_a = tmp_path / "a.png"
    path_b = tmp_path / "b.png"
    path_a.write_bytes(b"image-content-a")
    path_b.write_bytes(b"image-content-b")
    with _inject_fake_paddleocr(), \
            patch("servers.ocr.core.recognize_single", return_value="文本") as mock_single:
        result = recognize_texts([str(path_a), str(path_b)], lang="ch")
    assert result == ["文本", "文本"]
    assert mock_single.call_count == 2


def test_recognize_texts_lang_is_part_of_cache_key(tmp_path):
    """同一文件不同 lang 视为不同键，recognize_single 各执行一次。"""
    path = tmp_path / "img.png"
    path.write_bytes(b"lang-key-test")
    with _inject_fake_paddleocr(), \
            patch("servers.ocr.core.recognize_single", return_value="文本") as mock_single:
        recognize_texts([str(path)], lang="ch")
        recognize_texts([str(path)], lang="en")
    assert mock_single.call_count == 2


def test_recognize_texts_cache_key_independent_of_path(tmp_path):
    """同内容复制成不同路径，第二次调用仍命中缓存，recognize_single 只执行一次。"""
    path_a = tmp_path / "copy-a.png"
    path_b = tmp_path / "copy-b.png"
    path_a.write_bytes(b"identical-content")
    path_b.write_bytes(b"identical-content")
    with _inject_fake_paddleocr(), \
            patch("servers.ocr.core.recognize_single", return_value="文本") as mock_single:
        first = recognize_texts([str(path_a)], lang="ch")
        second = recognize_texts([str(path_b)], lang="ch")
    assert first == ["文本"]
    assert second == ["文本"]
    assert mock_single.call_count == 1
