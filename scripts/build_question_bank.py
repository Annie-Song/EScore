"""分类题库构建脚本（F7）：把 GAOKAO-Bench 全量主客观题入库为可检索题库。

用法：
    python scripts/build_question_bank.py                  # 默认库 ./output/question_bank.db
    python scripts/build_question_bank.py --db /tmp/q.db   # 指定数据库文件
    python scripts/build_question_bank.py --source-dir /path/to/gaokao  # 覆盖题库源目录
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# 支持 `python scripts/xxx.py` 直接运行：把项目根加入 sys.path，使 services/utils 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import question_bank
from services.question_bank_store import QuestionBankStore
from utils import config


def main(argv: list[str] | None = None) -> int:
    """构建题库入库主流程，返回进程退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default=config.QUESTION_BANK_DB_PATH, help="数据库文件路径"
    )
    parser.add_argument(
        "--source-dir",
        default=config.QUESTION_BANK_GAOKAO_DIR,
        help="GAOKAO-Bench 根目录（覆盖后重扫题库源）",
    )
    args = parser.parse_args(argv)

    config.QUESTION_BANK_GAOKAO_DIR = args.source_dir
    questions = question_bank.iter_gaokao_bank()
    store = QuestionBankStore(args.db)
    inserted = store.insert_many(questions)

    subject_counts = Counter(q.subject for q in questions)
    difficulty_counts = Counter(q.difficulty for q in questions)
    print(f"[构建] 入库 {inserted} 题（复核 count={store.count()}）")
    print("[构建] 按科目分布：")
    for subject, count in subject_counts.most_common():
        print(f"  {subject}: {count}")
    print("[构建] 按难度分布：")
    for difficulty, count in difficulty_counts.most_common():
        print(f"  {difficulty}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
