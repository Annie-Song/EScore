"""评分模块：在线 DeepSeek 精排 + 离线本地相似度兜底。

1.1 版本中离线兜底使用 difflib 文本相似度占位；
1.2 微服务重构时替换为向量嵌入（bi-encoder）+ 余弦相似度。
"""
import difflib
import logging
from typing import Optional

from grade import get_points

logger = logging.getLogger(__name__)


def offline_score(reference: str, answer: str) -> float:
    """离线本地相似度，返回 0-100 的百分制分数。

    当前用 difflib.SequenceMatcher 做字面相似度，仅作占位；
    语义级相似度需在 1.2 替换为向量嵌入方案。
    """
    if not reference or not answer:
        return 0.0
    ratio = difflib.SequenceMatcher(None, reference.strip(), answer.strip()).ratio()
    return round(ratio * 100, 1)


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
