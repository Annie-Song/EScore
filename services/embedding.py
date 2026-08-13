"""向量嵌入服务：用多语言 bi-encoder 计算句向量，供离线语义匹配使用。"""
import logging
from typing import List

import numpy as np

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
