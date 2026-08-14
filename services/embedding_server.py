"""向量嵌入微服务：独立 FastAPI 进程，提供句向量编码与语义相似度 HTTP 接口。

A8 拆分：把模型加载与参考答案缓存逻辑从 services/embedding.py 迁移到服务端，
客户端改为通过 HTTP 调用，替代同进程内直接调用。模型懒加载，首次请求才加载。
"""
import logging
import threading

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

from utils import config

logger = logging.getLogger(__name__)

# 多语言 MiniLM 模型，中英文双覆盖，离线语义粗筛用
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
# 完整 HuggingFace 仓库 ID（缓存目录按此命名，缓存检测与加载都必须用它而非简称）
REPO_ID = "sentence-transformers/" + MODEL_NAME

app = FastAPI(title="Embedding Service")

_model = None

# 参考答案嵌入缓存：按文本键缓存，批量批改时参考嵌入只编码一次
_REF_CACHE: dict[str, np.ndarray] = {}
_REF_CACHE_LOCK = threading.Lock()


class _EncodeRequest(BaseModel):
    """/encode 请求体：待编码文本列表。"""
    texts: list[str]


class _SimilarityRequest(BaseModel):
    """/similarity 请求体：参考文本与学生答案。"""
    reference: str
    answer: str


class _EncodeReferenceRequest(BaseModel):
    """/encode_reference 请求体：参考文本。"""
    text: str


class _BatchSimilarityRequest(BaseModel):
    """/batch_similarity 请求体：参考文本与学生答案列表。"""
    reference: str
    answers: list[str]


def _get_model():
    """懒加载 sentence-transformers 模型。

    模型已缓存时用 snapshot_download 解析本地快照目录，再把本地路径传给
    SentenceTransformer，使 transformers 判定为本地模型（_is_local=True），
    跳过对 huggingface.co 的 is_base_mistral 网络探测（否则离线环境会超时）。
    未缓存时回退到在线下载。
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError
        try:
            local_path = snapshot_download(REPO_ID, local_files_only=True)
        except LocalEntryNotFoundError:
            logger.info("向量模型未缓存，在线下载: %s", REPO_ID)
            _model = SentenceTransformer(REPO_ID)
        else:
            logger.info("向量模型已缓存，离线加载: %s", local_path)
            _model = SentenceTransformer(local_path)
    return _model


def _cached_encode_reference(reference: str) -> np.ndarray:
    """编码参考答案为归一化句向量，按文本键缓存（线程安全）。

    缓存只是优化：达到 config.REF_CACHE_MAX 上限时整体清空后重算，保证内存有界。
    空文本返回空向量（size 0），由调用方按 0 分兜底。
    """
    if not reference:
        return np.empty(0, dtype=np.float32)
    with _REF_CACHE_LOCK:
        cached = _REF_CACHE.get(reference)
        if cached is not None:
            return cached
        if len(_REF_CACHE) >= config.REF_CACHE_MAX:
            _REF_CACHE.clear()
        vector = _get_model().encode([reference], normalize_embeddings=True)[0]
        _REF_CACHE[reference] = vector
        return vector


def _to_float_list(vector: np.ndarray) -> list[float]:
    """把句向量 ndarray 序列化为 JSON 可传输的 float 列表。"""
    return vector.astype(float).tolist()


@app.get("/health")
def health() -> dict:
    """健康检查：返回服务状态与加载的模型名。"""
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/encode")
def encode(payload: _EncodeRequest) -> dict:
    """编码文本列表为归一化向量矩阵。"""
    vectors = _get_model().encode(payload.texts, normalize_embeddings=True)
    return {"vectors": [_to_float_list(vec) for vec in vectors]}


@app.post("/similarity")
def similarity(payload: _SimilarityRequest) -> dict:
    """计算参考文本与学生答案的语义相似度（归一化向量点积）。"""
    ref_vector = _cached_encode_reference(payload.reference)
    if ref_vector.size == 0:
        return {"score": 0.0}
    answer_vector = _get_model().encode([payload.answer], normalize_embeddings=True)[0]
    return {"score": float(np.dot(ref_vector, answer_vector))}


@app.post("/encode_reference")
def encode_reference(payload: _EncodeReferenceRequest) -> dict:
    """编码参考文本并写入缓存；空文本返回空数组。"""
    return {"vector": _to_float_list(_cached_encode_reference(payload.text))}


@app.post("/batch_similarity")
def batch_similarity(payload: _BatchSimilarityRequest) -> dict:
    """批量计算参考文本与各答案的相似度，返回与 answers 等长的分数列表。"""
    if not payload.answers:
        return {"scores": []}
    ref_vector = _cached_encode_reference(payload.reference)
    if ref_vector.size == 0:
        return {"scores": [0.0] * len(payload.answers)}
    answer_vectors = _get_model().encode(payload.answers, normalize_embeddings=True)
    return {"scores": [float(np.dot(ref_vector, vec)) for vec in answer_vectors]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config.EMBEDDING_SERVICE_HOST,
        port=config.EMBEDDING_SERVICE_PORT,
        log_level="info",
    )
