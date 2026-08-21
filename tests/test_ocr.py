"""OCR 识别服务单元测试。"""
from unittest.mock import patch

import pytest

import services.ocr_core as ocr_module
from services.ocr_core import recognize_texts


class _FakeOCR:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def ocr(self, path, cls=True):
        self.calls.append(path)
        return self._results.pop(0)


def test_recognize_texts_joins_lines_and_shares_instance():
    fake = _FakeOCR([
        [[[None, ("第一行", 0.9)], [None, ("第二行", 0.8)]]],
        [[[None, ("参考答案", 0.9)]]],
    ])
    with patch("services.ocr_core._load_paddleocr", return_value=fake):
        result = recognize_texts(["a.jpg", "b.jpg"], lang="ch")
    assert result == ["第一行\n第二行", "参考答案"]
    assert fake.calls == ["a.jpg", "b.jpg"]


def test_recognize_texts_handles_no_text_result():
    fake = _FakeOCR([[None], [None]])
    with patch("services.ocr_core._load_paddleocr", return_value=fake):
        result = recognize_texts(["a.jpg", "b.jpg"])
    assert result == ["", ""]


def test_recognize_lines_of_returns_lines_and_avg_confidence():
    """recognize_lines_of 返回 (lines, avg_confidence) 二元组，不做增强决策。"""
    fake = _FakeOCR([[[[None, ("行一", 0.8)], [None, ("行二", 0.6)]]]])
    with patch("services.ocr_core._load_paddleocr", return_value=fake):
        lines, avg = ocr_module.recognize_lines_of("a.jpg", fake)
    assert lines == [("行一", 0.8), ("行二", 0.6)]
    assert avg == pytest.approx(0.7)


def test_recognize_single_high_confidence_returns_joined_text():
    """recognize_single 高置信度（≥ 阈值）→ 直接返回按行拼接文本，不触发增强。"""
    fake = _FakeOCR([[[[None, ("第一", 0.9)], [None, ("第二", 0.8)]]]])
    with patch("services.ocr_core._load_paddleocr", return_value=fake):
        text = ocr_module.recognize_single("a.jpg")
    assert text == "第一\n第二"


def test_ocr_instance_forwards_to_loader_with_lang():
    """ocr_instance 转发到 _load_paddleocr 并按语言返回实例。"""
    fake = _FakeOCR([])
    with patch("services.ocr_core._load_paddleocr", return_value=fake) as mock_load:
        instance = ocr_module.ocr_instance("en")
    assert instance is fake
    mock_load.assert_called_once_with("en")
