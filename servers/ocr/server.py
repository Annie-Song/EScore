"""OCR 微服务：独立 FastAPI 进程，提供文字识别、作业分区与增强识别 HTTP 接口。

A11 拆分：把 OCR 识别（services/ocr.py）、智能分区（services/segment.py）与整图
增强去重识别（services/region_ocr.py）从主进程迁移到独立服务，业务调用方零改动。
识别/分区/增强均为重量级操作，模型懒加载，首次请求才真正加载 PaddleOCR。
"""

# 必须先于 paddle（OCR）加载 torch，避免两者在 Windows 同进程的 DLL 冲突：
# 若 paddle 先加载，torch 的 shm.dll 会报 WinError 127。此导入确保 torch 的
# 运行库先进入进程，paddle 随后加载时可复用，二者才能共存。paddleocr 懒加载，
# 此时不会真正触发。
import torch  # noqa: F401

from fastapi import FastAPI
from pydantic import BaseModel

from servers.ocr import core as ocr_core
from servers.ocr import region as region_ocr
from servers.ocr import segment
from backend.core import config

app = FastAPI(title="OCR Service")


class _RecognizeTextsRequest(BaseModel):
    """/recognize_texts 请求体：待识别图片路径列表与 OCR 语言。"""
    paths: list[str]
    lang: str


class _SegmentRequest(BaseModel):
    """/segment_image 请求体：待分区图片路径。"""
    path: str


class _CropRequest(BaseModel):
    """/crop_region 请求体：源图路径、裁剪区域 bbox 与输出路径。"""
    src: str
    bbox: list[int]
    dst: str


class _RegionsSharedEnhanceRequest(BaseModel):
    """/regions_with_shared_enhance 请求体：整图路径、语言与区域列表。"""
    image_path: str
    lang: str
    regions: list[dict]


@app.get("/health")
def health() -> dict:
    """健康检查：返回服务状态与服务名。"""
    return {"status": "ok", "service": "ocr"}


@app.get("/ready")
def _ready() -> dict:
    """就绪检查：强制加载 ch/en 两套 PaddleOCR，供 Docker 编排等待模型就绪（/health 不触发）。"""
    ocr_core.ocr_instance('ch')
    ocr_core.ocr_instance('en')
    return {"status": "ready", "service": "ocr"}


@app.post("/recognize_texts")
def recognize_texts(payload: _RecognizeTextsRequest) -> dict:
    """识别多张图片文字，返回按行拼接的文本列表；空列表短路返回空结果。"""
    if not payload.paths:
        return {"texts": []}
    texts = ocr_core.recognize_texts(payload.paths, lang=payload.lang)
    return {"texts": texts}


@app.post("/segment_image")
def segment_image(payload: _SegmentRequest) -> dict:
    """水平投影分区图片，返回区域列表；bbox 由 tuple 转 list 以 JSON 序列化。"""
    regions = segment.segment_image(payload.path)
    return {
        "regions": [
            {"index": region["index"], "bbox": list(region["bbox"])}
            for region in regions
        ]
    }


@app.post("/crop_region")
def crop_region(payload: _CropRequest) -> dict:
    """按 bbox 裁剪图片区域写入 dst，返回落盘路径。"""
    dst = segment.crop_region(payload.src, tuple(payload.bbox), payload.dst)
    return {"dst": dst}


@app.post("/regions_with_shared_enhance")
def regions_with_shared_enhance(payload: _RegionsSharedEnhanceRequest) -> dict:
    """整图增强去重识别各区域；增强不可用或失败返回 {"regions": None} 供客户端降级。"""
    regions = region_ocr.regions_with_shared_enhance(
        payload.image_path,
        payload.lang,
        payload.regions,
    )
    return {"regions": regions}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config.OCR_SERVICE_HOST,
        port=config.OCR_SERVICE_PORT,
        log_level="info",
    )
