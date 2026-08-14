"""ESRGAN 图像增强服务：对低质量图片做 4x 超分，供 OCR 低置信度重识别使用。

本服务为备选增强功能：权重文件缺失或加载失败时静默降级（_model 保持 None、
log warning），不抛异常；调用方通过 is_available() 判断是否可用。
"""
import logging
import os

import cv2
import numpy as np
import torch

from services.rrdbnet_arch import RRDBNet
from utils import config

logger = logging.getLogger(__name__)

# 模块级单例：模型加载成功后缓存，加载失败保持 None（备选功能，静默降级）
_model = None
# 权重缺失或加载失败只告警一次，避免低置信度图片多时重复刷日志
_load_warned = False


def _get_model() -> object:
    """懒加载 ESRGAN 模型并缓存为模块级单例，返回模型；不可用时返回 None。

    权重文件不存在或加载失败时不抛异常，保持 _model 为 None 并 log warning，
    使增强功能静默降级，不影响 OCR 主流程。权重后续补齐后重试可加载成功。
    """
    global _model, _load_warned
    if _model is not None:
        return _model
    if not os.path.exists(config.ENHANCE_WEIGHTS_PATH):
        if not _load_warned:
            logger.warning("ESRGAN 权重文件不存在: %s，增强功能不可用", config.ENHANCE_WEIGHTS_PATH)
            _load_warned = True
        return None
    try:
        net = RRDBNet(3, 3, scale=4, num_feat=64, num_block=23, num_grow_ch=32)
        state_dict = torch.load(config.ENHANCE_WEIGHTS_PATH, map_location="cpu", weights_only=True)
        # Real-ESRGAN 官方权重最外层为 params_ema，需解包后再载入
        if "params_ema" in state_dict:
            state_dict = state_dict["params_ema"]
        net.load_state_dict(state_dict, strict=True)
        net.eval()
        _model = net
        logger.info("ESRGAN 模型加载成功")
    except Exception as exc:
        if not _load_warned:
            logger.warning("ESRGAN 模型加载失败，增强功能降级: %s", exc)
            _load_warned = True
    return _model


def is_available() -> bool:
    """模型是否可用：已加载，或权重文件存在且加载成功。"""
    return _get_model() is not None


def enhance_image(src_path: str, dst_path: str) -> str:
    """对 src_path 图片做 4x 超分，写入 dst_path 并返回 dst_path。

    模型不可用时抛 RuntimeError("ESRGAN 模型不可用")，由调用方决定降级；
    模型可用但推理出错时异常向上传播，同样由调用方捕获降级。
    """
    model = _get_model()
    if model is None:
        raise RuntimeError("ESRGAN 模型不可用")
    img = cv2.imread(src_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法读取图片: {src_path}")
    output = _super_resolution(img, model)
    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    cv2.imwrite(dst_path, output)
    return dst_path


def _super_resolution(img: np.ndarray, model: object) -> np.ndarray:
    """对单张 BGR 图做超分前向，返回 4x 后的 BGR uint8 图像（CPU 推理）。

    处理链路：BGR 归一化 → BGR 转 RGB → 转 Tensor → 前向 → clamp → 转回
    OpenCV BGR 格式，与原 ESRGAN 脚本 super_resolution 保持一致。
    """
    img = img * 1.0 / 255
    img = torch.from_numpy(np.transpose(img[:, :, [2, 1, 0]], (2, 0, 1))).float()
    img_lr = img.unsqueeze(0)
    with torch.no_grad():
        output = model(img_lr).data.squeeze().float().cpu().clamp_(0, 1).numpy()
    output = np.transpose(output[[2, 1, 0], :, :], (1, 2, 0))
    output = (output * 255.0).round().astype(np.uint8)
    return output
