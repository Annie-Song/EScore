"""评分模块：在线 DeepSeek 精排 + 离线向量嵌入语义相似度兜底。"""
import logging
from typing import Optional

from services.deepseek import get_points
from services.embedding import semantic_similarity

logger = logging.getLogger(__name__)


def offline_score(reference: str, answer: str) -> float:
    """离线语义相似度，返回 0-100 的百分制分数。"""
    if not reference or not answer:
        return 0.0
    score = semantic_similarity(reference, answer)
    return round(max(0.0, min(1.0, score)) * 100, 1)


def online_score(reference: str, answer: str) -> Optional[float]:
    """在线 DeepSeek 评分，返回 0-100 的百分制分数；失败返回 None。"""
    raw = get_points(reference, answer)
    if raw is None:
        return None
    return round(raw * 100, 1)


def grade_answer(reference: str, answer: str, use_online: bool) -> dict:
    """按在线/离线模式评分，返回结构化结果。

    返回字典包含 score（0-100 分数）、method（online/offline）、
    degraded（在线失败是否降级到离线）。
    """
    if use_online:
        score = online_score(reference, answer)
        if score is not None:
            return {"score": score, "method": "online", "degraded": False}
        score = offline_score(reference, answer)
        logger.warning("在线评分失败，已降级为离线评分")
        return {"score": score, "method": "offline", "degraded": True}
    return {"score": offline_score(reference, answer), "method": "offline", "degraded": False}
