"""OCR HTTP 客户端：调用独立 FastAPI 微服务完成文字识别、分区裁剪与增强识别。

A11 拆分：OCR 服务端实现（services/ocr_core.py）、智能分区（services/segment.py）
与整图增强去重识别（services/region_ocr.py）已迁至独立进程，本模块仅通过 HTTP 调用
服务端端点，不再同进程持有 PaddleOCR 模型。服务不可达时抛 RuntimeError
（fail-fast），绝不静默降级或返回默认结果。
"""
import threading
from typing import Optional

import httpx

from backend.core import config

# 微服务基址与超时：首次请求含模型加载，超时给足 60s
_BASE = config.OCR_SERVICE_URL
_TIMEOUT = 60.0

_client: Optional[httpx.Client] = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    """懒加载共享 HTTP 客户端（线程安全，用锁保护）。

    httpx.Client 不发起网络连接，仅在真正请求时才建立，懒加载无副作用。
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(timeout=_TIMEOUT)
    return _client


def _post(path: str, payload: dict) -> dict:
    """POST 请求服务端并解析 JSON 响应；网络错误/非 2xx/解析失败一律抛 RuntimeError。"""
    url = f"{_BASE}{path}"
    try:
        resp = _get_client().post(url, json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"OCR 微服务不可达: {url}，请先启动 python -m servers.ocr.server"
        ) from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        raise RuntimeError(
            f"OCR 微服务返回异常状态码 {resp.status_code}: {url}，"
            f"请先启动 python -m servers.ocr.server"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError(f"OCR 微服务响应 JSON 解析失败: {url}") from exc


def recognize_texts(image_paths: list[str], lang: str = 'ch') -> list[str]:
    """识别多张图片文字，返回按行拼接的文本列表；空列表本地短路返回空列表。

    签名与旧版进程内实现一致，app/routes.py 与 services/batch.py 零改动。
    """
    if not image_paths:
        return []
    data = _post("/recognize_texts", {"paths": image_paths, "lang": lang})
    if "texts" not in data:
        raise RuntimeError(f"OCR 微服务响应缺字段 'texts': {_BASE}/recognize_texts")
    return list(data["texts"])


def segment_image(path: str) -> list[dict]:
    """分区图片返回区域列表；每项含 index 与 bbox list[int]。"""
    data = _post("/segment_image", {"path": path})
    if "regions" not in data:
        raise RuntimeError(f"OCR 微服务响应缺字段 'regions': {_BASE}/segment_image")
    return list(data["regions"])


def crop_region(image_path: str, bbox: tuple, out_path: str) -> str:
    """按 bbox 裁剪图片区域写入 out_path，返回落盘路径。"""
    data = _post(
        "/crop_region",
        {"src": image_path, "bbox": list(bbox), "dst": out_path},
    )
    if "dst" not in data:
        raise RuntimeError(f"OCR 微服务响应缺字段 'dst': {_BASE}/crop_region")
    return data["dst"]


def regions_with_shared_enhance(
    image_path: str,
    lang: str,
    regions: list[dict],
) -> Optional[list[dict]]:
    """整图增强去重识别各区域；服务端降级时 regions 为 null → 返回 None。

    保持旧版降级语义：返回 None 由调用方降级回逐区原路径。
    """
    data = _post(
        "/regions_with_shared_enhance",
        {"image_path": image_path, "lang": lang, "regions": regions},
    )
    if "regions" not in data:
        raise RuntimeError(
            f"OCR 微服务响应缺字段 'regions': {_BASE}/regions_with_shared_enhance"
        )
    if data["regions"] is None:
        return None
    return list(data["regions"])
