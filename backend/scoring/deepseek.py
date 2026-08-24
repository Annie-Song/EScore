"""DeepSeek 在线评分客户端：调用大模型对答案语义打分。"""
import json
import os
import logging
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

load_dotenv()

_client: Optional[OpenAI] = None


def _ensure_ssl_cert() -> None:
    """清除指向不存在文件的 SSL_CERT_FILE，让 httpx 回退到 certifi 默认证书。

    conda 在 Windows 上可能把 SSL_CERT_FILE 指向不存在的 ssl/cacert.pem，
    导致 httpx 建 SSL 上下文时报 FileNotFoundError（[Errno 2]）。
    """
    cert_file = os.environ.get("SSL_CERT_FILE")
    if cert_file and not os.path.exists(cert_file):
        os.environ.pop("SSL_CERT_FILE", None)
        logger.warning("SSL_CERT_FILE 指向不存在的文件 %s，已清除并回退默认证书", cert_file)


def _get_client() -> OpenAI:
    """懒加载 OpenAI 客户端，避免导入模块时因缺少密钥而崩溃。"""
    global _client
    if _client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "未找到 DEEPSEEK_API_KEY 环境变量，请复制 .env.example 为 .env 并填入密钥"
            )
        _ensure_ssl_cert()
        _client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return _client


def get_client() -> OpenAI:
    """获取懒加载的 DeepSeek OpenAI 客户端（评分与评测作答生成复用）。"""
    return _get_client()


def _clamp_score(score: float) -> float:
    """把评分钳制到 [0, 1] 区间，防止模型输出越界值污染最终分数。"""
    return max(0.0, min(1.0, score))


def _parse_score_content(content: Optional[str]) -> Optional[float]:
    """从 DeepSeek 的 content 字符串中解析 0.00-1.00 的评分。

    解析顺序（fail-fast，不伪造分数）：
        a. 剥掉可能的 ```json 围栏后 json.loads，取 dict 的 "score" 键；
        b. 裸数字浮点兜底（兼容模型偶发直接输出数字）；
        c. 都失败时记录原始输出并返回 None。

    参数:
        content (Optional[str]): 模型输出的原始 content 文本

    返回:
        Optional[float]: 钳制到 [0, 1] 的评分；解析失败返回 None。
    """
    if not content:
        return None
    stripped = content.strip()
    # 兼容 ```json 围栏输出：剥掉围栏再交给 json.loads
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip("`").strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict) and "score" in parsed:
            return _clamp_score(float(parsed["score"]))
    except (TypeError, ValueError):
        pass
    try:
        return _clamp_score(float(stripped))
    except (TypeError, ValueError):
        logger.warning("无法从 DeepSeek 响应中解析出分数，原始输出: %s", content)
        return None


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
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": """你是一个专业评分老师，按以下规则精确打分：
1. 完全符合参考答案语义给1.00分
2. 部分正确按比例评分（如覆盖3个要点中的2个给0.67）
3. 语义相同但表达不同仍给满分
4. 必须输出 JSON 格式：{"score": 0.85}，其中 score 为 0.00-1.00 之间的两位小数

示例：
参考：水的沸点是100℃
答案：水烧开需要100度 → {"score": 1.00}
答案：开水温度约一百度 → {"score": 0.95}
答案：水会沸腾 → {"score": 0.30}"""
                },
                {
                    "role": "user",
                    "content": f"""
[参考答案]
{reference}

[学生答案]
{query}

请严格输出 JSON 评分（score 为 0.00-1.00 两位小数）："""
                }
            ],
            temperature=0.1,
            stream=False
        )

        content = response.choices[0].message.content
        logger.info("Deepseek原始输出: %s", content)
        return _parse_score_content(content)

    except Exception as e:
        logger.error("Deepseek API调用失败: %s", e)
        return None
