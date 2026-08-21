"""services/ocr_core.py 低置信度 ESRGAN 增强重识别单元测试。

通过 mock services.enhance.is_available / enhance_image（真实权重不存在），
并用假 PaddleOCR 控制每次识别返回的 (text, score)，全程离线独立运行。
"""
import os
import shutil
from unittest.mock import patch

import pytest

import services.enhance as enhance_module
import services.ocr_core as ocr_module
from services.ocr_core import recognize_texts
from utils import config


class _FakeOCR:
    """按序返回预置识别结果的假 OCR，记录每次调用路径。"""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def ocr(self, path: str, cls: bool = True) -> list:
        self.calls.append(path)
        return self._results.pop(0)


@pytest.fixture(autouse=True)
def _reset_ocr_enhance_state():
    """每轮测试前后复位模块级状态，并清理 output/enhance 运行时残留。"""
    enhance_module._model = None
    enhance_module._load_warned = False
    ocr_module._enhance_warned = False
    ocr_module._ocr_instances.clear()
    yield
    shutil.rmtree(config.ENHANCE_OUTPUT_FOLDER, ignore_errors=True)
    enhance_module._model = None
    enhance_module._load_warned = False
    ocr_module._enhance_warned = False
    ocr_module._ocr_instances.clear()


def test_low_confidence_enhance_available_better_uses_enhanced():
    """低置信度且增强可用、增强后置信度更高 → 采用增强重识别结果。"""
    fake = _FakeOCR([
        [[[None, ("原文本", 0.3)]]],
        [[[None, ("增强文本", 0.9)]]],
    ])
    with patch.object(ocr_module, "_load_paddleocr", return_value=fake):
        with patch.object(enhance_module, "is_available", return_value=True):
            with patch.object(
                enhance_module, "enhance_image", side_effect=lambda src, dst: dst
            ) as mock_enhance:
                result = recognize_texts(["a.jpg"], lang="ch")
    assert result == ["增强文本"]
    assert mock_enhance.call_count == 1
    src_arg, dst_arg = mock_enhance.call_args[0]
    assert src_arg == "a.jpg"
    assert dst_arg.startswith(config.ENHANCE_OUTPUT_FOLDER)
    assert os.path.basename(dst_arg).endswith(".png")
    stem = os.path.splitext(os.path.basename(dst_arg))[0]
    assert len(stem) == 32 and all(c in "0123456789abcdef" for c in stem)
    assert fake.calls == ["a.jpg", dst_arg]


def test_low_confidence_enhance_worse_keeps_original():
    """低置信度且增强可用但增强后置信度更低 → 保留原识别结果。"""
    fake = _FakeOCR([
        [[[None, ("原文本", 0.5)]]],
        [[[None, ("增强文本", 0.4)]]],
    ])
    with patch.object(ocr_module, "_load_paddleocr", return_value=fake):
        with patch.object(enhance_module, "is_available", return_value=True):
            with patch.object(
                enhance_module, "enhance_image", side_effect=lambda src, dst: dst
            ) as mock_enhance:
                result = recognize_texts(["a.jpg"])
    assert result == ["原文本"]
    assert mock_enhance.call_count == 1
    assert fake.calls == ["a.jpg", mock_enhance.call_args[0][1]]


def test_low_confidence_enhance_unavailable_skips_enhance():
    """低置信度但增强不可用 → 走普通识别，不调用 enhance_image。"""
    fake = _FakeOCR([
        [[[None, ("原文本", 0.3)]]],
    ])
    with patch.object(ocr_module, "_load_paddleocr", return_value=fake):
        with patch.object(enhance_module, "is_available", return_value=False):
            with patch.object(enhance_module, "enhance_image") as mock_enhance:
                result = recognize_texts(["a.jpg"])
    assert result == ["原文本"]
    mock_enhance.assert_not_called()
    assert fake.calls == ["a.jpg"]
    assert ocr_module._enhance_warned is True


def test_high_confidence_does_not_trigger_enhance():
    """高置信度（avg>=0.6）→ 不触发增强。"""
    fake = _FakeOCR([
        [[[None, ("清晰文本", 0.9)]]],
    ])
    with patch.object(ocr_module, "_load_paddleocr", return_value=fake):
        with patch.object(enhance_module, "is_available", return_value=True):
            with patch.object(enhance_module, "enhance_image") as mock_enhance:
                result = recognize_texts(["a.jpg"])
    assert result == ["清晰文本"]
    mock_enhance.assert_not_called()
    assert fake.calls == ["a.jpg"]
    assert ocr_module._enhance_warned is False


def test_enhance_retry_enhance_step_raises_degrades_to_original():
    """增强步骤抛异常 → 降级为原识别结果，不向上抛（备选功能降级）。"""
    fake = _FakeOCR([
        [[[None, ("原文本", 0.2)]]],
    ])
    with patch.object(ocr_module, "_load_paddleocr", return_value=fake):
        with patch.object(enhance_module, "is_available", return_value=True):
            with patch.object(
                enhance_module, "enhance_image", side_effect=RuntimeError("mock enhance fail")
            ):
                result = recognize_texts(["a.jpg"])
    assert result == ["原文本"]


def test_enhance_retry_recognition_raises_degrades_to_original():
    """增强后重识别抛异常 → 降级为原识别结果，不向上抛。"""
    fake = _FakeOCR([
        [[[None, ("原文本", 0.2)]]],
        RuntimeError("mock re-recognition fail"),
    ])
    with patch.object(ocr_module, "_load_paddleocr", return_value=fake):
        with patch.object(enhance_module, "is_available", return_value=True):
            with patch.object(
                enhance_module, "enhance_image", side_effect=lambda src, dst: dst
            ):
                result = recognize_texts(["a.jpg"])
    assert result == ["原文本"]


def test_multiple_images_enhance_output_written_with_uuid():
    """多张图顺序识别，增强输出写入 ENHANCE_OUTPUT_FOLDER 且为 uuid4 命名。"""
    fake = _FakeOCR([
        [[[None, ("第一", 0.3)]]],
        [[[None, ("第一增强", 0.9)]]],
        [[[None, ("第二", 0.9)]]],
    ])

    def _fake_enhance(src: str, dst: str) -> str:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(b"fake-enhance-output")
        return dst

    with patch.object(ocr_module, "_load_paddleocr", return_value=fake):
        with patch.object(enhance_module, "is_available", return_value=True):
            with patch.object(enhance_module, "enhance_image", side_effect=_fake_enhance):
                result = recognize_texts(["a.jpg", "b.jpg"])
    assert result == ["第一增强", "第二"]
    assert len(fake.calls) == 3
    assert fake.calls[0] == "a.jpg"
    assert fake.calls[2] == "b.jpg"
    enhance_dst = fake.calls[1]
    assert os.path.dirname(enhance_dst) == config.ENHANCE_OUTPUT_FOLDER
    assert os.path.isfile(enhance_dst)
    assert os.path.basename(enhance_dst).endswith(".png")
    stem = os.path.splitext(os.path.basename(enhance_dst))[0]
    assert len(stem) == 32 and all(c in "0123456789abcdef" for c in stem)
