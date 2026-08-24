"""校本题库存储（F10）：继承 QuestionBankStore，提供校本题创建与删除。

校本题归属 school_id；删除限题主本人、本校 school_admin、全局 admin，
本层只做存储操作，权限判定在路由层完成。
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime

from services.question_bank import BankQuestion
from services.question_bank_store import QuestionBankStore


class SchoolQuestionStore(QuestionBankStore):
    """校本题数据访问类：复用基类连接与批量插入，新增创建与删除。"""

    def create(self, fields: dict, school_id: str, created_by: str) -> dict:
        """写入一条校本题并返回完整 dict（含 qid/school_id/created_by/created_at）。

        qid 用 uuid4 hex 加 sch_ 前缀；source_type 固定 "school"、
        source_file 空串；created_at 用当前 ISO 时间。
        """
        question = BankQuestion(
            qid=f"sch_{uuid.uuid4().hex}",
            subject=fields["subject"],
            qtype=fields["qtype"],
            grade=fields.get("grade", ""),
            year=fields.get("year", ""),
            region=fields.get("region", ""),
            difficulty=fields["difficulty"],
            source_type="school",
            source_file="",
            question=fields["question"],
            answer=fields["answer"],
            analysis=fields.get("analysis", ""),
            score=int(fields["score"]),
            index=0,
            school_id=school_id,
            created_by=created_by,
            created_at=datetime.now().isoformat(),
        )
        self.insert_many([question])
        return asdict(question)

    def delete(self, qid: str) -> int:
        """按 qid 删除题目，返回受影响行数（0 表示不存在）。"""
        with self._session() as conn:
            cursor = conn.execute(
                "DELETE FROM question_bank WHERE qid=?", (qid,)
            )
        return cursor.rowcount
