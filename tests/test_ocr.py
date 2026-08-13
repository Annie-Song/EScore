"""OCR 识别服务单元测试。"""
from unittest.mock import patch

from services.ocr import recognize_texts


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
    with patch("services.ocr._load_paddleocr", return_value=fake):
        result = recognize_texts(["a.jpg", "b.jpg"], lang="ch")
    assert result == ["第一行\n第二行", "参考答案"]
    assert fake.calls == ["a.jpg", "b.jpg"]


def test_recognize_texts_handles_no_text_result():
    fake = _FakeOCR([[None], [None]])
    with patch("services.ocr._load_paddleocr", return_value=fake):
        result = recognize_texts(["a.jpg", "b.jpg"])
    assert result == ["", ""]
