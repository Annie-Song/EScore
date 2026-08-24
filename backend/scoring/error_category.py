"""错因归类服务：规则分档 + AI 细类混合级联归类。

默认按分数规则分档（零依赖、可离线）；ai_mode 开启且分数落入模糊带时，
调用 DeepSeek 对错因做细分类，失败降级回规则档并记录 warning。
"""
import json
import logging
from typing import Tuple

from backend.core import config

logger = logging.getLogger(__name__)

# 规则分档类别
CATEGORY_NONE = "未作答"
CATEGORY_CONCEPT = "概念错误"
CATEGORY_PARTIAL = "要点遗漏"
CATEGORY_MOSTLY = "部分正确"
CATEGORY_MASTER = "掌握良好"

# AI 可选细类（追加在规则类别之后）
CATEGORY_CALCULATION = "计算错误"
CATEGORY_MISSING_STEP = "步骤缺失"
CATEGORY_UNCLEAR = "表达不清"

# 固定分类全集：规则类别 + AI 细类，AI 输出类别必须落在其中
AI_CATEGORIES = frozenset({
    CATEGORY_NONE,
    CATEGORY_CONCEPT,
    CATEGORY_PARTIAL,
    CATEGORY_MOSTLY,
    CATEGORY_MASTER,
    CATEGORY_CALCULATION,
    CATEGORY_MISSING_STEP,
    CATEGORY_UNCLEAR,
})


def rule_category(score: float) -> str:
    """按分数区间映射错误分类，分档规则与需求保持一致。"""
    if score <= 0:
        return CATEGORY_NONE
    if score < 30:
        return CATEGORY_CONCEPT
    if score < 60:
        return CATEGORY_PARTIAL
    if score < 85:
        return CATEGORY_MOSTLY
    return CATEGORY_MASTER


def classify_error(
    reference: str,
    answer: str,
    score: float,
    ai_mode: bool = False,
) -> Tuple[str, str]:
    """混合级联归类，返回 (category, reason)。

    默认走规则分档（reason 为空串）；ai_mode 为真且分数落在
    config.ERROR_AI_BAND_LOW/HIGH 模糊带内时调用 AI 细分类，异常降级规则档。
    """
    category = rule_category(score)
    if not ai_mode or not (config.ERROR_AI_BAND_LOW <= score <= config.ERROR_AI_BAND_HIGH):
        return category, ""
    try:
        return classify_ai(reference, answer)
    except Exception as exc:  # noqa: BLE001 - AI 归类失败降级规则档，与项目降级风格一致
        logger.warning("AI 错因归类失败，降级为规则分档: %s", exc)
        return category, ""


def classify_ai(reference: str, answer: str) -> Tuple[str, str]:
    """调用 DeepSeek 对错因做细分类，返回 (category, reason)。

    要求模型严格输出 JSON {"category":"...","reason":"..."}；category 不在
    AI_CATEGORIES 或 JSON 解析失败时抛 ValueError，由 classify_error 捕获降级。
    """
    from backend.scoring.deepseek import _get_client

    client = _get_client()
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一位专业批改老师，请从以下固定分类中为错因选择一个最贴切的类别："
                    f"{'、'.join(sorted(AI_CATEGORIES))}。必须严格输出 JSON，格式为"
                    "{\"category\":\"...\",\"reason\":\"...\"}，reason 用一句话说明错因，"
                    "不要输出任何其他内容。"
                ),
            },
            {
                "role": "user",
                "content": f"[参考答案]\n{reference}\n\n[学生答案]\n{answer}",
            },
        ],
        temperature=0.1,
        stream=False,
    )
    content = response.choices[0].message.content
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"AI 错因输出不是合法 JSON: {content!r}") from exc
    category = payload.get("category")
    reason = payload.get("reason", "")
    if category not in AI_CATEGORIES:
        raise ValueError(f"AI 错因类别不在分类表内: {category!r}")
    return category, reason
