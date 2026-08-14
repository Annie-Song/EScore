"""评测作答生成脚本（A9）：用 DeepSeek 为 GAOKAO-Bench 题目生成优/中/差三档作答。

金标为构造定义（提示词指定质量档位），benchmark 用独立 MiniLM 语义信号校验档位真实性，
全程不用 DeepSeek 评判自身。结果增量缓存到 config.EVAL_ANSWERS_PATH，之后 benchmark 纯离线。
需要 DEEPSEEK_API_KEY（.env 或环境变量）与外网，由用户在本会话执行 `! python ...`。

用法：
    python scripts/generate_eval_answers.py                # 全部题目三档生成（增量续跑）
    python scripts/generate_eval_answers.py --limit 5      # 仅前 5 题（试跑/控制成本）
    python scripts/generate_eval_answers.py --tiers good medium  # 只生成指定档位
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 支持 `python scripts/xxx.py` 直接运行：把项目根加入 sys.path，使 services/utils 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.deepseek import get_client
from services.eval_set import load_gaokao_questions
from utils import config

# 每档作答的生成提示：只输出作答文本，不做质量标注（避免自评污染评测）
_TIER_PROMPTS = {
    "good": (
        "你是作答这道题的学生。请写一份优秀的作答：内容完整、要点覆盖全面、"
        "表达通顺，与参考答案语义一致但用自己的话表达。只输出作答文本，"
        "不要任何解释或质量标注。"
    ),
    "medium": (
        "你是作答这道题的学生。请写一份中等质量的作答：只覆盖部分要点，"
        "表达一般，有遗漏或不完全准确。只输出作答文本，不要任何解释或质量标注。"
    ),
    "bad": (
        "你是作答这道题的学生。请写一份低质量的作答：答非所问、要点缺失或"
        "包含明显错误。只输出作答文本，不要任何解释或质量标注。"
    ),
}
_TIERS = tuple(_TIER_PROMPTS.keys())


def _generate_answer(question: str, reference: str, tier: str) -> str:
    """调用 DeepSeek 生成指定档位的作答文本。"""
    client = get_client()
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": _TIER_PROMPTS[tier]},
            {
                "role": "user",
                "content": f"[题目]\n{question}\n\n[参考答案]\n{reference}\n\n请写出该档作答：",
            },
        ],
        temperature=0.7,
        stream=False,
    )
    text = resp.choices[0].message.content
    if not text or not text.strip():
        raise RuntimeError(f"DeepSeek 返回空作答（tier={tier}）")
    return text.strip()


def _load_existing(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    """读取已生成的作答缓存，返回 {(subject, index): tiers}，用于增量续跑。"""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        (item["subject"], item["index"]): item["tiers"]
        for item in data.get("answers", [])
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 题（0=全部）")
    parser.add_argument("--tiers", nargs="+", default=list(_TIERS), help="要生成的档位")
    parser.add_argument("--out", default=config.EVAL_ANSWERS_PATH, help="输出 JSON 路径")
    args = parser.parse_args(argv)

    questions = load_gaokao_questions()
    if args.limit:
        questions = questions[: args.limit]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cache = _load_existing(out_path)
    skipped = 0
    for q in questions:
        key = (q.subject, q.index)
        existing = cache.setdefault(key, {})
        needed = [t for t in args.tiers if t not in existing]
        if not needed:
            skipped += 1
            continue
        for tier in needed:
            existing[tier] = _generate_answer(q.question, q.answer, tier)
        # 增量落盘：中断后重跑只补缺失档位，不重复花费 API
        _write_cache(out_path, cache)
        print(f"[生成] {q.subject} #{q.index} 档位={needed}")

    _write_cache(out_path, cache)
    total = sum(len(t) for t in cache.values())
    print(f"[完成] 共 {len(cache)} 题 {total} 档作答，已缓存到 {out_path}（跳过已生成 {skipped} 题）")
    return 0


def _write_cache(path: Path, cache: dict[tuple[str, int], dict[str, str]]) -> None:
    """按 answers.json 规范写盘，保留 subject/index/question/reference 上下文。"""
    questions = load_gaokao_questions()
    by_key = {(q.subject, q.index): q for q in questions}
    payload = {
        "meta": {
            "source": "gaokao-bench",
            "tiers": list(_TIERS),
            "count": len(cache),
        },
        "answers": [
            {
                "subject": sub,
                "index": idx,
                "question": by_key[(sub, idx)].question,
                "reference": by_key[(sub, idx)].answer,
                "tiers": tiers,
            }
            for (sub, idx), tiers in sorted(cache.items())
            if (sub, idx) in by_key
        ],
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(main())
