"""评分模块：在线 DeepSeek 精排 + 离线向量嵌入语义相似度兜底。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from services.deepseek import get_points
from services.embedding import semantic_similarity
from utils.config import (
    BAND_HIGH,
    BAND_LOW,
    DEFAULT_ROUTING_PRESET,
    LOW_THRESHOLD,
    ROUTING_MODE,
    ROUTING_PRESETS,
)

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


@dataclass(frozen=True)
class RoutingConfig:
    """一次路由决策的完整参数：策略族 + 阈值（frozen 不可变）。"""
    mode: str = ROUTING_MODE
    low: float = LOW_THRESHOLD
    band_low: float = BAND_LOW
    band_high: float = BAND_HIGH


def resolve_preset(name: str) -> RoutingConfig:
    """按预设名解析路由配置；未知名抛 ValueError（fail-fast，不塞默认值）。"""
    try:
        return RoutingConfig(**ROUTING_PRESETS[name])
    except KeyError:
        raise ValueError(f"未知路由预设: {name!r}，可选 {sorted(ROUTING_PRESETS)}") from None


def should_route(offline_score: float, routing: RoutingConfig | None = None) -> bool:
    """判断离线粗筛分是否应路由到 DeepSeek 精排。

    routing 缺省时读取模块级常量（ROUTING_MODE/LOW_THRESHOLD/BAND_*），与旧行为一致，
    测试可 patch services.scoring.ROUTING_MODE 生效；显式传入 routing 则按给定配置决策
    （双档预设与扫描工具复用）。
    """
    if routing is None:
        # 必须在调用时读模块全局，不能用 RoutingConfig() 类默认值（那会在 import 时绑定常量，
        # patch 模块级常量后不生效）
        routing = RoutingConfig(mode=ROUTING_MODE, low=LOW_THRESHOLD,
                                band_low=BAND_LOW, band_high=BAND_HIGH)
    if routing.mode == "threshold":
        return offline_score < routing.low
    if routing.mode == "band":
        return routing.band_low <= offline_score <= routing.band_high
    return False


def grade_answer(reference: str, answer: str, force_online: bool,
                 quality_mode: str = DEFAULT_ROUTING_PRESET,
                 allow_online: bool = True) -> dict:
    """按在线/离线级联模式评分，返回结构化结果。

    quality_mode 选择路由预设（fast/quality），决定低分路由阈值；
    force_online 时预设仅用于校验不参与路由决策。
    allow_online=False 时禁用在线路径：显式精排与自动路由均优雅降级为离线，
    不抛错、不调 DeepSeek。

    返回字典包含 score（0-100 分数）、method（online/offline）、
    degraded（在线失败是否降级到离线）、routed（是否由离线粗筛自动路由精排）。
    """
    routing = resolve_preset(quality_mode)
    if not allow_online:
        # free 档无在线精排权限：显式精排与自动路由均不进在线路径，直接返回离线分
        offline = offline_score(reference, answer)
        return {"score": offline, "method": "offline", "degraded": False, "routed": False}
    if force_online:
        score = online_score(reference, answer)
        if score is not None:
            return {"score": score, "method": "online", "degraded": False, "routed": False}
        score = offline_score(reference, answer)
        logger.warning("在线评分失败，已降级为离线评分")
        return {"score": score, "method": "offline", "degraded": True, "routed": False}

    offline = offline_score(reference, answer)
    if not should_route(offline, routing):
        return {"score": offline, "method": "offline", "degraded": False, "routed": False}

    score = online_score(reference, answer)
    if score is not None:
        return {"score": score, "method": "online", "degraded": False, "routed": True}
    logger.warning("级联精排失败，已降级为离线评分")
    return {"score": offline, "method": "offline", "degraded": True, "routed": True}
