"""向量嵌入 HTTP 客户端：调用独立 FastAPI 微服务计算句向量与语义相似度。

A8 拆分：模型加载与参考答案缓存逻辑已迁至 services/embedding_server.py，
本模块仅通过 HTTP 调用服务端端点，不再同进程持有模型。
服务不可达时抛 RuntimeError（fail-fast），绝不静默降级或返回默认分数。
"""
import threading
from typing import Optional

import httpx
import numpy as np

from backend.core import config

# 微服务基址与超时：首次请求含模型加载，超时给足 60s
_BASE = config.EMBEDDING_SERVICE_URL
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
            f"向量嵌入服务不可达: {url}，请先启动 python -m servers.embedding.server"
        ) from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        raise RuntimeError(
            f"向量嵌入服务返回异常状态码 {resp.status_code}: {url}，"
            f"请先启动 python -m servers.embedding.server"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError(f"向量嵌入服务响应 JSON 解析失败: {url}") from exc


def encode(texts: list[str]) -> np.ndarray:
    """将文本列表编码为归一化句向量矩阵，返回 float32 的 ndarray。"""
    data = _post("/encode", {"texts": texts})
    if "vectors" not in data:
        raise RuntimeError(f"向量嵌入服务响应缺字段 'vectors': {_BASE}/encode")
    return np.asarray(data["vectors"], dtype=np.float32)


def semantic_similarity(reference: str, answer: str) -> float:
    """计算两段文本的语义相似度，返回 0-1 之间的浮点数。"""
    data = _post("/similarity", {"reference": reference, "answer": answer})
    if "score" not in data:
        raise RuntimeError(f"向量嵌入服务响应缺字段 'score': {_BASE}/similarity")
    return float(data["score"])


def encode_reference(reference: str) -> np.ndarray:
    """编码参考答案为归一化句向量；空文本本地短路返回空向量（size 0）。

    空文本不发起 HTTP，语义与旧实现一致，调用方按 0 分兜底。
    """
    if not reference:
        return np.empty(0, dtype=np.float32)
    data = _post("/encode_reference", {"text": reference})
    if "vector" not in data:
        raise RuntimeError(f"向量嵌入服务响应缺字段 'vector': {_BASE}/encode_reference")
    return np.asarray(data["vector"], dtype=np.float32)


def batch_similarities(reference: str, answers: list[str]) -> list[float]:
    """批量计算参考答案与各学生答案的语义相似度，返回与 answers 等长的列表。

    answers 为空本地短路返回空列表（不发起 HTTP），其余请求服务端批量计算。
    """
    if not answers:
        return []
    data = _post("/batch_similarity", {"reference": reference, "answers": answers})
    if "scores" not in data:
        raise RuntimeError(f"向量嵌入服务响应缺字段 'scores': {_BASE}/batch_similarity")
    return [float(score) for score in data["scores"]]
