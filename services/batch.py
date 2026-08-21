"""批量批改编排：OCR 参考图 → 逐份分区识别 → 批量评分 → 错因归类 → 单事务落库。"""
import logging
import os
import uuid
from datetime import datetime
from typing import List

from services.ocr import recognize_texts
from services.store import (
    BATCH_STATUS_FAILED,
    BATCH_STATUS_RUNNING,
    BATCH_STATUS_SUCCEEDED,
    GradeRecord,
    default_store,
)
from services.task_store import update_task
from utils import config

logger = logging.getLogger(__name__)


def run_batch_job(
    task_id: str,
    reference_path: str,
    work_paths: List[str],
    lang: str,
    enable_segment: bool,
    error_ai_mode: bool,
    quality_mode: str = config.DEFAULT_ROUTING_PRESET,
    user_id: str = "",
) -> None:
    """执行一次批量批改任务：OCR 参考图、逐份分区评分、错因归类并落库。

    quality_mode 选择路由预设（fast/quality），决定批量评分时的低分路由阈值。
    user_id 非空时把批次归属写入 user_batches；写入失败仅记日志，不阻断批改。
    全程不吞异常：任何未处理异常都在末尾统一捕获，标记任务失败后重新抛出，
    供后台线程的异常钩子记录完整堆栈。
    """
    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    store = default_store()
    batch_created = False
    records: list[GradeRecord] = []
    try:
        reference_text = recognize_texts([reference_path], lang=lang)[0]
        now_iso = datetime.now().isoformat()
        store.save_batch(batch_id, reference_text, BATCH_STATUS_RUNNING, 0, now_iso)
        batch_created = True
        if user_id:
            try:
                from services.user_activity_store import default_user_activity_store

                default_user_activity_store().link_batch(user_id, task_id, batch_id)
            except Exception:
                logger.exception("user_batches 映射写入失败，不影响批改")

        total = len(work_paths)
        for index, work_path in enumerate(work_paths, start=1):
            update_task(
                task_id,
                current_item=index,
                progress=round(index / total * 100),
                message=f"正在批改第 {index}/{total} 份作业",
            )
            regions = _regions_of(work_path, lang, enable_segment)
            work_texts = [region["work_text"] for region in regions]
            results = _scores_for(reference_text, work_texts, quality_mode)
            for region, result in zip(regions, results):
                category, reason = _classify_for(
                    reference_text, region["work_text"], result["score"], error_ai_mode
                )
                records.append(
                    GradeRecord(
                        record_id=uuid.uuid4().hex,
                        batch_id=batch_id,
                        question_no=region["question_no"],
                        work_text=region["work_text"],
                        answer_text=reference_text,
                        score=result["score"],
                        method=result["method"],
                        degraded=result["degraded"],
                        routed=result["routed"],
                        created_at=now_iso,
                        error_category=category,
                        error_reason=reason,
                    )
                )

        store.save_records(records)
        store.update_batch_status(batch_id, BATCH_STATUS_SUCCEEDED, len(records))
        update_task(
            task_id,
            status="succeeded",
            progress=100,
            result={
                "batch_id": batch_id,
                "record_count": len(records),
                "total_items": total,
            },
            finished_at=datetime.now().isoformat(),
        )

    except Exception as exc:  # noqa: BLE001 - 顶线兜底标记失败并重抛，不吞异常
        logger.exception("批量批改任务失败: task_id=%s", task_id)
        update_task(
            task_id,
            status="failed",
            error=str(exc),
            finished_at=datetime.now().isoformat(),
        )
        if batch_created:
            store.update_batch_status(batch_id, BATCH_STATUS_FAILED, len(records))
        raise


def _regions_of(path: str, lang: str, enable_segment: bool) -> list[dict]:
    """把一份作业图切分为区域识别结果，每个元素含 question_no 与 work_text。

    enable_segment 且分区超过 1 个区域时，先尝试整图增强去重识别（整图低置信度
    时增强一次、各区域共享）；该路径不可用或降级时，逐区域从原图裁剪后各自 OCR；
    否则整图 OCR，题号记为 1。裁剪文件写入 config.SEGMENT_OUTPUT_FOLDER，
    文件名用 uuid 防并发冲突。
    """
    if enable_segment:
        from services.ocr import crop_region, segment_image

        regions = segment_image(path)
        if len(regions) > 1:
            from services.ocr import regions_with_shared_enhance

            shared = regions_with_shared_enhance(path, lang, regions)
            if shared is not None:
                return shared
            os.makedirs(config.SEGMENT_OUTPUT_FOLDER, exist_ok=True)
            result = []
            for region in regions:
                crop_path = os.path.join(
                    config.SEGMENT_OUTPUT_FOLDER, f"{uuid.uuid4().hex}.png"
                )
                crop_region(path, region["bbox"], crop_path)
                text = recognize_texts([crop_path], lang=lang)[0]
                result.append({"question_no": region["index"], "work_text": text})
            return result
    text = recognize_texts([path], lang=lang)[0]
    return [{"question_no": 1, "work_text": text}]


def _scores_for(reference_text: str, work_texts: list[str], quality_mode: str) -> list[dict]:
    """对一份作业的多个区域文本批量评分；参考文本为空时统一给 0 分（离线）。

    quality_mode 选择路由预设（fast/quality），透传给 grade_batch 决定低分路由阈值。
    """
    if not reference_text:
        return [
            {"score": 0.0, "method": "offline", "degraded": False, "routed": False}
            for _ in work_texts
        ]
    from services.batch_scoring import grade_batch

    return grade_batch(
        reference_text, work_texts, force_online=False, quality_mode=quality_mode
    )


def _classify_for(
    reference_text: str, work_text: str, score: float, ai_mode: bool
) -> tuple[str, str]:
    """对单条记录做错因归类，返回 (category, reason)；懒导入便于离线测试 mock。"""
    from services.error_category import classify_error

    return classify_error(reference_text, work_text, score, ai_mode=ai_mode)
