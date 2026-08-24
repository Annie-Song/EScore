"""services/enhance.py ESRGAN 图像增强单元测试（备选功能）。

权重缺失/加载失败应静默降级（is_available 返回 False 且不抛异常），
模型可用时 enhance_image 正确写出 4x 超分结果。全程 mock 外部依赖，
可离线独立运行。
"""
from unittest.mock import patch

import numpy as np
import pytest
import torch

import servers.ocr.enhance as enhance_module
from servers.ocr import enhance


class _FakeCallableModel:
    """可调用假模型：forward 返回 4x 尺寸的零张量，模拟 ESRGAN 超分前向。

    servers.ocr.enhance 使用 model(img_lr) 调用，故需要 __call__ 而非 forward。
    """

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        b, c, h, w = x.shape
        return torch.zeros((b, c, h * 4, w * 4))


@pytest.fixture(autouse=True)
def _reset_enhance_state():
    """每轮测试前后复位模块级单例与告警标志，隔离用例间状态。"""
    enhance_module._model = None
    enhance_module._load_warned = False
    yield
    enhance_module._model = None
    enhance_module._load_warned = False


def test_is_available_weights_missing_returns_false_without_raise(tmp_path):
    """权重文件缺失时 is_available 返回 False 且不抛异常。"""
    missing_path = str(tmp_path / "no_such_RRDB_ESRGAN_x4.pth")
    with patch("backend.core.config.ENHANCE_WEIGHTS_PATH", missing_path):
        assert enhance.is_available() is False
    assert enhance_module._model is None
    assert enhance_module._load_warned is True


def test_enhance_image_model_unavailable_raises_runtime_error(tmp_path):
    """模型不可用时 enhance_image 抛 RuntimeError，消息含“ESRGAN 模型不可用”。"""
    missing_path = str(tmp_path / "missing_model.pth")
    with patch("backend.core.config.ENHANCE_WEIGHTS_PATH", missing_path):
        with pytest.raises(RuntimeError, match="ESRGAN 模型不可用"):
            enhance.enhance_image("src.png", "dst.png")


def test_enhance_image_model_available_writes_dst_and_returns_path(tmp_path):
    """模型可用时 enhance_image 调用 cv2.imwrite 写出 4x 结果并返回 dst 路径。"""
    src = str(tmp_path / "src.png")
    dst_dir = tmp_path / "sub"
    dst = str(dst_dir / "dst.png")
    with patch.object(enhance_module, "_get_model", return_value=_FakeCallableModel()):
        with patch.object(
            enhance_module.cv2, "imread", return_value=np.zeros((8, 8, 3), dtype=np.uint8)
        ) as mock_imread:
            with patch.object(enhance_module.cv2, "imwrite") as mock_imwrite:
                with patch.object(enhance_module.os, "makedirs") as mock_makedirs:
                    result = enhance.enhance_image(src, dst)
    assert result == dst
    mock_imread.assert_called_once_with(src, enhance_module.cv2.IMREAD_COLOR)
    assert mock_imwrite.call_count == 1
    written_path, written_img = mock_imwrite.call_args[0]
    assert written_path == dst
    assert written_img.dtype == np.uint8
    assert written_img.shape == (32, 32, 3)  # 8x8 输入 → 4x 超分
    mock_makedirs.assert_called_once_with(str(dst_dir), exist_ok=True)


def test_super_resolution_output_shape_4x_uint8():
    """_super_resolution 输出为 uint8 且尺寸为输入的 4 倍。"""
    img = np.zeros((10, 12, 3), dtype=np.uint8)
    out = enhance_module._super_resolution(img, _FakeCallableModel())
    assert out.dtype == np.uint8
    assert out.shape == (40, 48, 3)


def test_load_failure_keeps_none_and_retry_succeeds(tmp_path):
    """torch.load 抛异常后 _model 保持 None、is_available False；随后可重试成功。"""
    weights = tmp_path / "model.pth"
    weights.write_bytes(b"fake-weights")
    fake_state = {"weight": "fake"}
    with patch("backend.core.config.ENHANCE_WEIGHTS_PATH", str(weights)):
        with patch.object(
            enhance_module.torch, "load", side_effect=[RuntimeError("corrupt file"), fake_state]
        ):
            with patch.object(enhance_module, "RRDBNet") as mock_rrdb:
                net = mock_rrdb.return_value
                # 第一次加载失败：静默降级
                assert enhance.is_available() is False
                assert enhance_module._model is None
                assert enhance_module._load_warned is True
                # 权重修复后重试可成功加载
                assert enhance.is_available() is True
                assert enhance_module._model is net
                assert mock_rrdb.call_count == 2
                net.load_state_dict.assert_called_once_with(fake_state, strict=True)
                net.eval.assert_called_once_with()
