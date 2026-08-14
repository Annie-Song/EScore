"""向量嵌入服务：用多语言 bi-encoder 计算句向量，供离线语义匹配使用。"""
import logging
import threading
from typing import List

import numpy as np

from utils import config

logger = logging.getLogger(__name__)

# 多语言 MiniLM 模型，中英文双覆盖，离线语义粗筛用
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
# 完整 HuggingFace 仓库 ID（缓存目录按此命名，缓存检测与加载都必须用它而非简称）
REPO_ID = "sentence-transformers/" + MODEL_NAME

_model = None


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


def encode(texts: List[str]) -> np.ndarray:
    """将文本列表编码为归一化句向量矩阵。"""
    return _get_model().encode(texts, normalize_embeddings=True)


def semantic_similarity(reference: str, answer: str) -> float:
    """计算两段文本的语义相似度，返回 0-1 之间的浮点数。"""
    embeddings = encode([reference, answer])
    return float(np.dot(embeddings[0], embeddings[1]))


# 参考答案嵌入缓存：按文本键缓存，批量批改时参考嵌入只编码一次
_REF_CACHE: dict[str, np.ndarray] = {}
_REF_CACHE_LOCK = threading.Lock()


def encode_reference(reference: str) -> np.ndarray:
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
        vector = encode([reference])[0]
        _REF_CACHE[reference] = vector
        return vector


def batch_similarities(reference: str, answers: list[str]) -> list[float]:
    """批量计算参考答案与各学生答案的余弦相似度，返回与 answers 等长的列表。

    参考嵌入走缓存仅编码一次，全部答案一次批编码后做点积。answers 为空返回空列表。
    """
    if not answers:
        return []
    ref_vector = encode_reference(reference)
    if ref_vector.size == 0:
        return [0.0] * len(answers)
    answer_vectors = encode(answers)
    return [float(np.dot(ref_vector, vec)) for vec in answer_vectors]
