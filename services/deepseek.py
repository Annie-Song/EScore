"""DeepSeek 在线评分客户端：调用大模型对答案语义打分。"""
import os
import re
import logging
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

load_dotenv()

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    """懒加载 OpenAI 客户端，避免导入模块时因缺少密钥而崩溃。"""
    global _client
    if _client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "未找到 DEEPSEEK_API_KEY 环境变量，请复制 .env.example 为 .env 并填入密钥"
            )
        _client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return _client


def get_points(reference: str, query: str) -> Optional[float]:
    """使用 DeepSeek 评估学生答案与参考答案的相似度。

    参数:
        reference (str): 参考答案文本
        query (str): 学生答案文本

    返回:
        Optional[float]: 0.00-1.00 之间的相似度分数；失败时返回 None。
    """
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": """你是一个专业评分老师，按以下规则精确打分：
    1. 完全符合参考答案语义给1.00分
    2. 部分正确按比例评分（如覆盖3个要点中的2个给0.67）
    3. 语义相同但表达不同仍给满分
    4. 必须输出0.00-1.00之间的两位小数

    示例：
    参考：水的沸点是100℃
    答案：水烧开需要100度 → 1.00
    答案：开水温度约一百度 → 0.95
    答案：水会沸腾 → 0.30"""
                },
                {
                    "role": "user",
                    "content": f"""
    [参考答案]
    {reference}

    [学生答案]
    {query}

    请严格输出0.00-1.00的数字评分："""
                }
            ],
            temperature=0.1,
            stream=False
        )

        score_str = response.choices[0].message.content
        logger.info("Deepseek原始输出: %s", score_str)

        try:
            return float(score_str)
        except (TypeError, ValueError):
            match = re.search(r"\d?\.\d{1,2}", score_str)
            if match:
                score = float(match.group())
                logger.info("从文本中提取的评分: %s", score)
                return score
            logger.warning("无法从Deepseek响应中提取评分")
            return None

    except Exception as e:
        logger.error("Deepseek API调用失败: %s", e)
        return None
