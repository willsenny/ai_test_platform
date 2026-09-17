"""
向量写入（Phase G）

把三类业务对象 embed 后写入 Qdrant：
- TestCase        → testcases      （保存时）
- TestStepResult  → step_results   （失败时）
- SelfHealLog     → heal_logs      （保存时）

所有写入均为 best-effort：Qdrant/embedding 不可用时仅记录日志，绝不阻断业务。
默认同步（内联）执行以保证演示确定性；RAG_INDEX_ASYNC=1 时提交到后台线程。
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from apps.rag.retriever import (
    COLLECTION_HEAL_LOGS,
    COLLECTION_STEP_RESULTS,
    COLLECTION_TESTCASES,
    upsert,
)

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-index")
_futures: list = []


def _async_enabled() -> bool:
    from apps.rag.retriever import _enabled

    return _enabled() and os.getenv("RAG_INDEX_ASYNC", "0").strip().lower() in ("1", "true", "yes")


def _submit(fn, *args) -> None:
    if _async_enabled():
        _futures.append(_executor.submit(fn, *args))
    else:
        fn(*args)


def flush(timeout: float | None = None) -> None:
    """等待后台索引任务完成（测试/演示收尾用）。"""
    for fut in list(_futures):
        try:
            fut.result(timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
    _futures.clear()


# ============================================================
# 文本化
# ============================================================
def testcase_text(case) -> str:
    parts = [str(getattr(case, "title", "") or "")]
    parts += [str(x) for x in (getattr(case, "preconditions", None) or [])]
    parts += [str(x) for x in (getattr(case, "tags", None) or [])]
    for step in getattr(case, "raw_steps", None) or getattr(case, "steps", None) or []:
        parts += [
            str(step.get("action", "")),
            str(step.get("selector", "")),
            str(step.get("value", "")),
            str(step.get("description", "")),
        ]
    for assertion in getattr(case, "assertions", None) or []:
        if isinstance(assertion, dict):
            parts += [
                str(assertion.get("type", "")),
                str(assertion.get("selector", "")),
                str(assertion.get("expected", "")),
            ]
        else:
            parts.append(str(assertion))
    return " ".join(p for p in parts if p).strip()


def failure_text(step) -> str:
    parts = [
        str(getattr(step, "phase", "") or ""),
        str(getattr(step, "action", "") or ""),
        str(getattr(step, "selector", "") or ""),
        str(getattr(step, "value", "") or ""),
        str(getattr(step, "expected", "") or ""),
        str(getattr(step, "actual", "") or ""),
        str(getattr(step, "error", "") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def heal_text(log) -> str:
    parts = [
        str(getattr(log, "failure_pattern", "") or ""),
        str(getattr(log, "fix_strategy", "") or ""),
        str(getattr(log, "last_detail", "") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


# ============================================================
# 写入
# ============================================================
def index_testcase(case) -> bool:
    try:
        from apps.rag.embedder import get_embedder

        text = testcase_text(case)
        if not text:
            return False
        embedder = get_embedder()
        payload = {
            "title": getattr(case, "title", ""),
            "project_id": getattr(case, "project_key", None)
            or getattr(case, "project_id", ""),
            "priority": getattr(case, "priority", ""),
            "tags": list(getattr(case, "tags", None) or []),
            "target_url": getattr(case, "target_url", ""),
            "source": getattr(case, "source", ""),
            "steps": getattr(case, "raw_steps", None) or getattr(case, "steps", None) or [],
            "assertions": list(getattr(case, "assertions", None) or []),
            "text": text,
        }
        return upsert(
            COLLECTION_TESTCASES,
            [{"id": int(case.pk), "vector": embedder.embed(text), "payload": payload}],
            embedder.dimension,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("index_testcase(%s) skipped: %s", getattr(case, "pk", "?"), exc)
        return False


def index_failure(step) -> bool:
    try:
        from apps.rag.embedder import get_embedder

        text = failure_text(step)
        if not text:
            return False
        embedder = get_embedder()
        payload = {
            "testcase_id": getattr(step, "testcase_id", None),
            "run_id": getattr(step, "run_id", None),
            "phase": getattr(step, "phase", ""),
            "action": getattr(step, "action", ""),
            "selector": getattr(step, "selector", ""),
            "value": getattr(step, "value", ""),
            "expected": getattr(step, "expected", ""),
            "actual": getattr(step, "actual", ""),
            "status": getattr(step, "status", ""),
            "error": getattr(step, "error", ""),
            "text": text,
        }
        return upsert(
            COLLECTION_STEP_RESULTS,
            [{"id": int(step.pk), "vector": embedder.embed(text), "payload": payload}],
            embedder.dimension,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("index_failure(%s) skipped: %s", getattr(step, "pk", "?"), exc)
        return False


def index_heal_log(log) -> bool:
    try:
        from apps.rag.embedder import get_embedder

        text = heal_text(log)
        if not text:
            return False
        embedder = get_embedder()
        payload = {
            "failure_pattern": getattr(log, "failure_pattern", ""),
            "fix_strategy": getattr(log, "fix_strategy", ""),
            "attempt_count": getattr(log, "attempt_count", 0),
            "success_count": getattr(log, "success_count", 0),
            "success_rate": getattr(log, "success_rate", 0.0),
            "last_detail": getattr(log, "last_detail", ""),
            "text": text,
        }
        return upsert(
            COLLECTION_HEAL_LOGS,
            [{"id": int(log.pk), "vector": embedder.embed(text), "payload": payload}],
            embedder.dimension,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("index_heal_log(%s) skipped: %s", getattr(log, "pk", "?"), exc)
        return False


def index_failures(steps: list) -> int:
    """批量索引失败步骤，返回成功条数。"""
    return sum(1 for step in steps if index_failure(step))


# ============================================================
# 信号回调（可异步）
# ============================================================
def schedule_testcase(case) -> None:
    _submit(index_testcase, case)


def schedule_failure(step) -> None:
    _submit(index_failure, step)


def schedule_heal_log(log) -> None:
    _submit(index_heal_log, log)


def dump_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
