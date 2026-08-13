"""向量嵌入服务：用多语言 bi-encoder 计算句向量，供离线语义匹配使用。"""
import logging
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

# 多语言 MiniLM 模型，中英文双覆盖，离线语义粗筛用
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

_model = None


def _get_model():
    """懒加载 sentence-transformers 模型，首次调用下载并加载权重。"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("加载向量嵌入模型: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode(texts: List[str]) -> np.ndarray:
    """将文本列表编码为归一化句向量矩阵。"""
    return _get_model().encode(texts, normalize_embeddings=True)


def semantic_similarity(reference: str, answer: str) -> float:
    """计算两段文本的语义相似度，返回 0-1 之间的浮点数。"""
    embeddings = encode([reference, answer])
    return float(np.dot(embeddings[0], embeddings[1]))
