"""批量批改编排单元测试：分区、评分、归类、落库全链路（外部依赖全 mock）。"""
import pytest
from unittest.mock import patch

import services.task_store as task_store
from services.batch import run_batch_job
from utils import config as config_module

_SEGMENT_REGIONS = [
    {"index": 1, "bbox": (0, 0, 10, 20)},
    {"index": 2, "bbox": (0, 20, 10, 20)},
]


@pytest.fixture(autouse=True)
def _reset_task_store():
    """每轮测试前清空任务注册表，保证用例隔离。"""
    task_store._tasks.clear()
    yield
    task_store._tasks.clear()


@pytest.fixture
def image_files(tmp_path):
    """构造一份参考答案图 + 两份作业图（文件内容无关，OCR 被 mock）。"""
    reference = tmp_path / "reference.jpg"
    work1 = tmp_path / "work1.jpg"
    work2 = tmp_path / "work2.jpg"
    for path in (reference, work1, work2):
        path.write_bytes(b"dummy-image")
    return {"reference": str(reference), "works": [str(work1), str(work2)]}


class _FakeStore:
    """内存版 GradeStore 替代品，记录 save_batch / save_records / update_batch_status 调用。"""

    def __init__(self):
        self.batches = {}
        self.saved_records = []
        self.status_updates = []

    def save_batch(self, batch_id, reference_text, status, total_questions, created_at):
        self.batches[batch_id] = {
            "batch_id": batch_id,
            "reference_text": reference_text,
            "status": status,
            "total_questions": total_questions,
            "created_at": created_at,
        }

    def save_records(self, records):
        self.saved_records.extend(records)

    def update_batch_status(self, batch_id, status, total_questions):
        self.status_updates.append((batch_id, status, total_questions))
        self.batches[batch_id]["status"] = status
        self.batches[batch_id]["total_questions"] = total_questions


def _fake_recognize(reference_path, reference_text, work_text):
    """构造 recognize_texts 假实现：参考答案返回指定文本，其余返回作业文本。"""

    def fake_recognize(image_paths, lang="ch"):
        if image_paths == [reference_path]:
            return [reference_text]
        return [work_text]

    return fake_recognize


def _result(score: float, method: str = "offline", degraded: bool = False,
            routed: bool = False) -> dict:
    return {"score": score, "method": method, "degraded": degraded, "routed": routed}


def test_run_batch_job_segmented_writes_four_records(image_files, tmp_path, monkeypatch):
    """enable_segment=True：2 份作业 × 各 2 区域 → 4 条记录落库、批次/任务成功。"""
    store = _FakeStore()
    task_id = task_store.create_task(2)
    monkeypatch.setattr(config_module, "SEGMENT_OUTPUT_FOLDER", str(tmp_path / "segments"))

    with patch("services.batch.recognize_texts",
               side_effect=_fake_recognize(image_files["reference"], "参考答案文本", "作业区域文本")), \
         patch("services.batch.default_store", return_value=store), \
         patch("services.segment.segment_image", return_value=_SEGMENT_REGIONS), \
         patch("services.segment.crop_region") as mock_crop, \
         patch("services.batch_scoring.grade_batch", side_effect=[
             [_result(80.0), _result(90.0, method="online", routed=True)],
             [_result(70.0), _result(85.0)],
         ]), \
         patch("services.error_category.classify_error", return_value=("要点遗漏", "理由")) as mock_classify, \
         patch("services.batch.update_task", wraps=task_store.update_task):
        run_batch_job(task_id, image_files["reference"], image_files["works"],
                      lang="ch", enable_segment=True, error_ai_mode=False)

    assert len(store.saved_records) == 4
    assert [r.question_no for r in store.saved_records] == [1, 2, 1, 2]
    assert [r.score for r in store.saved_records] == [80.0, 90.0, 70.0, 85.0]
    assert [r.method for r in store.saved_records] == ["offline", "online", "offline", "offline"]
    assert all(r.answer_text == "参考答案文本" for r in store.saved_records)
    assert all(r.error_category == "要点遗漏" for r in store.saved_records)
    assert mock_crop.call_count == 4
    assert mock_classify.call_count == 4

    task = task_store.get_task(task_id)
    assert task["status"] == "succeeded"
    assert task["progress"] == 100
    assert task["result"]["record_count"] == 4
    assert task["result"]["total_items"] == 2
    batch_id = task["result"]["batch_id"]
    assert batch_id.startswith("batch-")
    assert store.batches[batch_id]["status"] == "succeeded"
    assert store.status_updates == [(batch_id, "succeeded", 4)]


def test_run_batch_job_without_segment_one_record_per_work(image_files):
    """enable_segment=False：每份作业 1 条记录且 question_no=1。"""
    store = _FakeStore()
    task_id = task_store.create_task(2)

    with patch("services.batch.recognize_texts",
               side_effect=_fake_recognize(image_files["reference"], "参考答案文本", "整图文本")), \
         patch("services.batch.default_store", return_value=store), \
         patch("services.batch_scoring.grade_batch", side_effect=[
             [_result(70.0)],
             [_result(75.0)],
         ]), \
         patch("services.error_category.classify_error", return_value=("部分正确", "")), \
         patch("services.batch.update_task", wraps=task_store.update_task):
        run_batch_job(task_id, image_files["reference"], image_files["works"],
                      lang="ch", enable_segment=False, error_ai_mode=False)

    assert len(store.saved_records) == 2
    assert [r.question_no for r in store.saved_records] == [1, 1]
    assert [r.score for r in store.saved_records] == [70.0, 75.0]
    task = task_store.get_task(task_id)
    assert task["status"] == "succeeded"
    assert task["result"]["record_count"] == 2


def test_run_batch_job_empty_reference_skips_grade_batch(image_files):
    """参考文本为空：grade_batch 不被调用，score=0/method=offline，仍入库。"""
    store = _FakeStore()
    task_id = task_store.create_task(2)

    def empty_recognize(image_paths, lang="ch"):
        return [""]

    with patch("services.batch.recognize_texts", side_effect=empty_recognize), \
         patch("services.batch.default_store", return_value=store), \
         patch("services.batch_scoring.grade_batch") as mock_grade, \
         patch("services.error_category.classify_error", return_value=("未作答", "")) as mock_classify, \
         patch("services.batch.update_task", wraps=task_store.update_task):
        run_batch_job(task_id, image_files["reference"], image_files["works"],
                      lang="ch", enable_segment=False, error_ai_mode=False)

    mock_grade.assert_not_called()
    assert len(store.saved_records) == 2
    for record in store.saved_records:
        assert record.score == 0.0
        assert record.method == "offline"
        assert record.answer_text == ""
    assert mock_classify.call_count == 2
    task = task_store.get_task(task_id)
    assert task["status"] == "succeeded"
    assert task["result"]["record_count"] == 2


def test_run_batch_job_exception_marks_failed_and_reraises(image_files):
    """异常路径：任务标记 failed、error 非空、批次标记 failed、异常 re-raise。"""
    store = _FakeStore()
    task_id = task_store.create_task(2)
    ref_path = image_files["reference"]

    def failing_recognize(image_paths, lang="ch"):
        if image_paths == [ref_path]:
            return ["参考答案文本"]
        raise RuntimeError("OCR 失败")

    with patch("services.batch.recognize_texts", side_effect=failing_recognize), \
         patch("services.batch.default_store", return_value=store), \
         patch("services.batch.update_task", wraps=task_store.update_task):
        with pytest.raises(RuntimeError, match="OCR 失败"):
            run_batch_job(task_id, ref_path, image_files["works"],
                          lang="ch", enable_segment=False, error_ai_mode=False)

    task = task_store.get_task(task_id)
    assert task["status"] == "failed"
    assert task["error"] == "OCR 失败"
    batch_id = list(store.batches)[0]
    assert store.batches[batch_id]["status"] == "failed"
    assert store.status_updates == [(batch_id, "failed", 0)]


def test_run_batch_job_progress_tracks_current_item(image_files):
    """update_task 的 progress 随 current_item 更新。"""
    store = _FakeStore()
    task_id = task_store.create_task(2)

    with patch("services.batch.recognize_texts",
               side_effect=_fake_recognize(image_files["reference"], "参考答案文本", "文本")), \
         patch("services.batch.default_store", return_value=store), \
         patch("services.batch_scoring.grade_batch",
               return_value=[_result(60.0)]), \
         patch("services.error_category.classify_error", return_value=("部分正确", "")), \
         patch("services.batch.update_task", wraps=task_store.update_task) as mock_update:
        run_batch_job(task_id, image_files["reference"], image_files["works"],
                      lang="ch", enable_segment=False, error_ai_mode=False)

    progress_calls = [call for call in mock_update.call_args_list if "current_item" in call.kwargs]
    assert [call.kwargs["current_item"] for call in progress_calls] == [1, 2]
    assert [call.kwargs["progress"] for call in progress_calls] == [50, 100]
    assert progress_calls[0].kwargs["message"] == "正在批改第 1/2 份作业"
    assert progress_calls[1].kwargs["message"] == "正在批改第 2/2 份作业"
    assert task_store.get_task(task_id)["progress"] == 100


def test_run_batch_job_passes_quality_mode_to_grade_batch(image_files):
    """quality_mode 透传：run_batch_job 收到的 quality_mode 原样传给每次 grade_batch。"""
    store = _FakeStore()
    task_id = task_store.create_task(len(image_files["works"]))

    with patch("services.batch.recognize_texts",
               side_effect=_fake_recognize(image_files["reference"], "参考答案文本", "整图文本")), \
         patch("services.batch.default_store", return_value=store), \
         patch("services.batch_scoring.grade_batch", return_value=[_result(70.0)]) as mock_grade, \
         patch("services.error_category.classify_error", return_value=("部分正确", "")), \
         patch("services.batch.update_task", wraps=task_store.update_task):
        run_batch_job(task_id, image_files["reference"], image_files["works"],
                      lang="ch", enable_segment=False, error_ai_mode=False,
                      quality_mode="quality")

    assert mock_grade.call_count == len(image_files["works"])
    assert all(call.kwargs["quality_mode"] == "quality"
               for call in mock_grade.call_args_list)


def test_run_batch_job_default_quality_mode_is_fast(image_files):
    """缺省 quality_mode 为 fast（与 config.DEFAULT_ROUTING_PRESET 一致），透传给 grade_batch。"""
    store = _FakeStore()
    task_id = task_store.create_task(len(image_files["works"]))

    with patch("services.batch.recognize_texts",
               side_effect=_fake_recognize(image_files["reference"], "参考答案文本", "整图文本")), \
         patch("services.batch.default_store", return_value=store), \
         patch("services.batch_scoring.grade_batch", return_value=[_result(70.0)]) as mock_grade, \
         patch("services.error_category.classify_error", return_value=("部分正确", "")), \
         patch("services.batch.update_task", wraps=task_store.update_task):
        run_batch_job(task_id, image_files["reference"], image_files["works"],
                      lang="ch", enable_segment=False, error_ai_mode=False)

    assert mock_grade.call_count == len(image_files["works"])
    assert all(call.kwargs["quality_mode"] == "fast"
               for call in mock_grade.call_args_list)
