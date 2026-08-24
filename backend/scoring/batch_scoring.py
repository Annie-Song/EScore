"""批量评分模块：批量离线粗筛 + 在线精排级联，供批量批改编排复用。

从 services/scoring 拆出，使该文件保持 4 个公开函数；公共导入 API 不变
（backend.scoring.engine.batch_offline_scores/grade_batch 的调用方改为引用本模块）。
"""
import logging

from backend.scoring.embedding import batch_similarities
from backend.scoring.engine import offline_score, online_score, resolve_preset, should_route
from backend.core.config import DEFAULT_ROUTING_PRESET

logger = logging.getLogger(__name__)


def batch_offline_scores(reference: str, answers: list[str]) -> list[float]:
    """批量离线语义相似度评分，返回与 answers 等长的 0-100 百分制分数列表。

    参考嵌入走缓存只编码一次，全部答案一次批编码后点积得到相似度，
    再映射到百分制并 clamp、保留 1 位小数。
    """
    if not answers:
        return []
    similarities = batch_similarities(reference, answers)
    return [round(max(0.0, min(1.0, sim)) * 100, 1) for sim in similarities]


def grade_batch(reference: str, answers: list[str], force_online: bool,
                quality_mode: str = DEFAULT_ROUTING_PRESET) -> list[dict]:
    """批量级联评分，返回与 answers 一一对应的结果字典列表。

    quality_mode 选择路由预设（fast/quality），决定低分路由阈值；
    force_online 时预设仅用于校验不参与路由决策。
    语义与 grade_answer 一致：force_online 时逐条走在线评分，失败降级离线
    （degraded=True）；否则离线批量粗筛，should_route 为真的条目走 DeepSeek
    精排（成功 routed=True，失败降级离线并标记 degraded+routed）。
    """
    routing = resolve_preset(quality_mode)
    if force_online:
        results: list[dict] = []
        for answer in answers:
            score = online_score(reference, answer)
            if score is not None:
                results.append(
                    {"score": score, "method": "online", "degraded": False, "routed": False}
                )
                continue
            fallback = offline_score(reference, answer)
            logger.warning("在线评分失败，已降级为离线评分")
            results.append(
                {"score": fallback, "method": "offline", "degraded": True, "routed": False}
            )
        return results

    off_scores = batch_offline_scores(reference, answers)
    results = []
    for answer, offline in zip(answers, off_scores):
        if not should_route(offline, routing):
            results.append(
                {"score": offline, "method": "offline", "degraded": False, "routed": False}
            )
            continue
        score = online_score(reference, answer)
        if score is not None:
            results.append(
                {"score": score, "method": "online", "degraded": False, "routed": True}
            )
            continue
        logger.warning("级联精排失败，已降级为离线评分")
        results.append(
            {"score": offline, "method": "offline", "degraded": True, "routed": True}
        )
    return results
