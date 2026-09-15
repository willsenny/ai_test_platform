"""
执行器：通过 Playwright MCP 真执行结构化用例，写入批次/步骤级结果并生成报告。

链路（Phase E）：
- 创建 TestRun（一次执行批次）
- 按 raw_steps 逐条驱动 navigate / fill / click
- 按 assertions 调用 assert_text / assert_visible
- 每个 step / assertion 写一行 TestStepResult
- 汇总 TestCase.last_run_*（deprecated 摘要）+ TestRun 状态
- 生成 JSON + HTML 报告到 media/reports/run_{id}.{json,html}

浏览器未安装时状态记为 error，提示不阻断调用方。
"""
import asyncio
import json
import time

from asgiref.sync import sync_to_async


# ============================================================
# DB 读写（同步，供 sync_to_async 包装）
# ============================================================
def _load_case(case_id: int):
    from apps.testcases.models import TestCase

    return TestCase.objects.get(pk=case_id)


def _load_run(run_id: int):
    from .models import TestRun

    return TestRun.objects.get(pk=run_id)


def _create_run(project_id: str, goal: str, source: str, total_cases: int):
    from .models import TestRun

    return TestRun.objects.create(
        project_id=project_id,
        goal=goal,
        source=source,
        status=TestRun.Status.RUNNING,
        total_cases=total_cases,
    )


def _finalize_run(run_id: int, results: list[dict]) -> None:
    from django.utils import timezone

    from .models import TestRun

    statuses = [r.get("status") for r in results]
    if any(s == "error" for s in statuses):
        status = TestRun.Status.ERROR
    elif any(s == "fail" for s in statuses):
        status = TestRun.Status.FAIL
    elif statuses and all(s == "skipped" for s in statuses):
        status = TestRun.Status.SKIPPED
    else:
        status = TestRun.Status.PASS

    passed = sum(1 for s in statuses if s == "pass")
    TestRun.objects.filter(pk=run_id).update(
        status=status,
        passed_cases=passed,
        failed_cases=len(statuses) - passed,
        finished_at=timezone.now(),
    )


def _save_report_paths(run_id: int, json_path: str, html_path: str) -> None:
    from .models import TestRun

    TestRun.objects.filter(pk=run_id).update(
        report_json=json_path, report_html=html_path
    )


def _bulk_create_step_results(rows: list[dict]) -> list:
    from .models import TestStepResult

    objs = [TestStepResult(**row) for row in rows]
    if objs:
        TestStepResult.objects.bulk_create(objs)
    return objs


def _index_failed_steps(objs: list) -> int:
    """Phase G：bulk_create 不触发 post_save，显式索引失败步骤（best-effort）。"""
    try:
        from apps.rag.indexer import index_failures

        return index_failures([o for o in objs if o.status in ("fail", "error")])
    except Exception:  # noqa: BLE001 - RAG 不可用不阻断执行
        return 0


def _save_case_summary(case_id: int, status: str, summary: str) -> None:
    """DEPRECATED：保留最近一次执行摘要，明细见 TestStepResult。"""
    from django.utils import timezone

    from apps.testcases.models import TestCase

    TestCase.objects.filter(pk=case_id).update(
        last_run_status=status,
        last_run_log=summary,
        last_run_at=timezone.now(),
    )


# ============================================================
# 主入口
# ============================================================
async def execute_case(case_id: int, run_id: int | None = None) -> dict:
    """
    执行单条用例。

    run_id 为空时自建一个单用例批次（含报告）；否则并入给定批次。
    """
    case = await sync_to_async(_load_case)(case_id)

    own_run = run_id is None
    if own_run:
        run = await sync_to_async(_create_run)(case.project_id, case.title, "executor:single", 1)
        run_id = run.pk

    result = await _execute_case_into_run(case, run_id)

    if own_run:
        await sync_to_async(_finalize_run)(run_id, [result])
        run_obj = await sync_to_async(_load_run)(run_id)
        paths = await sync_to_async(_write_report)(run_obj)
        await sync_to_async(_save_report_paths)(run_id, paths["json"], paths["html"])
        result["report"] = paths

    return result


async def execute_cases(
    case_ids: list[int],
    *,
    goal: str = "",
    source: str = "executor:batch",
    project_id: str = "",
) -> dict:
    """一个批次执行多条用例，统一生成 TestRun + 报告。"""
    case_ids = [int(c) for c in case_ids]
    if not case_ids:
        return {
            "run_id": None,
            "status": "skipped",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "results": [],
            "report": {},
        }

    if not project_id:
        first = await sync_to_async(_load_case)(case_ids[0])
        project_id = first.project_id

    run = await sync_to_async(_create_run)(project_id, goal, source, len(case_ids))
    results = [await execute_case(cid, run_id=run.pk) for cid in case_ids]

    await sync_to_async(_finalize_run)(run.pk, results)
    run_obj = await sync_to_async(_load_run)(run.pk)
    paths = await sync_to_async(_write_report)(run_obj)
    await sync_to_async(_save_report_paths)(run.pk, paths["json"], paths["html"])

    passed = sum(1 for r in results if r["status"] == "pass")
    return {
        "run_id": run.pk,
        "status": run_obj.status,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
        "report": paths,
    }


def _write_report(run) -> dict:
    from .report import write_report

    return write_report(run)


# ============================================================
# 单用例执行（写入步骤明细）
# ============================================================
async def _execute_case_into_run(case, run_id: int) -> dict:
    steps = list(case.raw_steps or case.steps or [])
    assertions = list(case.assertions or [])
    target_url = case.target_url or ""

    rows: list[dict] = []
    log_lines: list[str] = []
    status = "pass"

    if not steps:
        status = "skipped"
        log_lines.append("no steps to execute")
    else:
        try:
            from apps.mcp.client import MCPClient

            async with MCPClient(servers=["playwright"]) as mcp:
                status = await _run_steps(mcp, case, run_id, steps, target_url, rows, log_lines)
                if status == "pass":
                    status = await _run_assertions(
                        mcp, case, run_id, assertions, rows, log_lines,
                        step_offset=len(steps),
                    )
        except Exception as exc:
            status = "error"
            log_lines.append(f"execution exception: {type(exc).__name__}: {exc}")

    step_objs = await sync_to_async(_bulk_create_step_results)(rows)
    await sync_to_async(_index_failed_steps)(step_objs)

    summary = f"run#{run_id} {status}: {len(rows)} rows"
    await sync_to_async(_save_case_summary)(case.pk, status, summary)

    return {
        "case_id": case.pk,
        "run_id": run_id,
        "status": status,
        "rows": len(rows),
        "log": "\n".join(log_lines),
    }


async def _run_steps(
    mcp, case, run_id: int, steps: list[dict], target_url: str,
    rows: list[dict], log_lines: list[str],
) -> str:
    """逐条执行 steps；返回 'pass' 或 'error'。"""
    for idx, step in enumerate(steps, 1):
        action = (step.get("action") or "").strip()
        selector = step.get("selector", "") or ""
        value = step.get("value", "") or ""
        description = step.get("description", "") or ""

        started = time.perf_counter()
        error = ""
        data: dict = {}
        try:
            if action in ("goto", "navigate"):
                result = await mcp.call_tool(
                    "playwright", "navigate", {"url": value or target_url}
                )
            elif action == "fill":
                result = await mcp.call_tool(
                    "playwright", "fill", {"selector": selector, "value": value}
                )
            elif action == "click":
                result = await mcp.call_tool(
                    "playwright", "click", {"selector": selector}
                )
            elif action == "wait":
                wait_ms = min(float(value or 500), 10000)
                await asyncio.sleep(wait_ms / 1000)
                result = {"waited_ms": int(wait_ms)}
            else:
                rows.append(_step_row(
                    case.pk, run_id, idx, "step", action, selector, value,
                    "", "", "skip", f"unknown action '{action}'", 0,
                ))
                log_lines.append(f"[step {idx}] SKIP unknown action '{action}'")
                continue
            data = _as_dict(result)
            if isinstance(data, dict) and data.get("error"):
                error = str(data["error"])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        duration_ms = int((time.perf_counter() - started) * 1000)
        step_status = "error" if error else "pass"
        rows.append(_step_row(
            case.pk, run_id, idx, "step", action, selector, value,
            "", _short(data) if not error else "", step_status, error, duration_ms,
        ))
        log_lines.append(
            f"[step {idx}] {action} {selector or value} "
            f"{('(' + description + ') ') if description else ''}"
            f"-> {error or _short(data)}"
        )
        if error:
            return "error"

    return "pass"


async def _run_assertions(
    mcp, case, run_id: int, assertions: list[dict],
    rows: list[dict], log_lines: list[str],
    step_offset: int = 0,
) -> str:
    """执行断言；返回 'pass' / 'fail' / 'error'。"""
    if not assertions:
        log_lines.append("[assert] no assertions, treated as pass")
        return "pass"

    outcome = "pass"
    for idx, assertion in enumerate(assertions, 1):
        a_type = assertion.get("type", "text_contains")
        selector = assertion.get("selector", "")
        expected = assertion.get("expected", "")
        row_index = step_offset + idx

        started = time.perf_counter()
        error = ""
        data: dict = {}
        try:
            if a_type in ("text_contains", "text_equals"):
                result = await mcp.call_tool(
                    "playwright",
                    "assert_text",
                    {
                        "selector": selector,
                        "expected": expected,
                        "mode": "equals" if a_type == "text_equals" else "contains",
                    },
                )
            elif a_type == "visible":
                result = await mcp.call_tool(
                    "playwright", "assert_visible", {"selector": selector}
                )
            else:
                rows.append(_step_row(
                    case.pk, run_id, row_index, "assert", a_type, selector, "",
                    expected, "", "skip", f"unknown assertion type '{a_type}'", 0,
                ))
                log_lines.append(f"[assert {idx}] SKIP unknown type '{a_type}'")
                continue
            data = _as_dict(result)
            if isinstance(data, dict) and data.get("error"):
                error = str(data["error"])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        duration_ms = int((time.perf_counter() - started) * 1000)
        actual = str(data.get("actual", "")) if isinstance(data, dict) else ""

        if error:
            step_status = "error"
            outcome = "error"
        elif isinstance(data, dict) and data.get("passed"):
            step_status = "pass"
        else:
            step_status = "fail"
            if outcome != "error":
                outcome = "fail"

        rows.append(_step_row(
            case.pk, run_id, row_index, "assert", a_type, selector, "",
            expected, actual, step_status, error, duration_ms,
        ))
        log_lines.append(
            f"[assert {idx}] {a_type} {selector} expected={expected!r} "
            f"actual={actual!r} -> {'error' if error else step_status}"
        )
        if outcome == "error":
            return "error"

    return outcome


def _step_row(
    case_id: int, run_id: int, index: int, phase: str, action: str,
    selector: str, value: str, expected: str, actual: str,
    status: str, error: str, duration_ms: int,
) -> dict:
    return {
        "run_id": run_id,
        "testcase_id": case_id,
        "step_index": index,
        "phase": phase,
        "action": action,
        "selector": selector,
        "value": value,
        "expected": expected,
        "actual": actual,
        "status": status,
        "error": error,
        "duration_ms": duration_ms,
    }


# ============================================================
# 工具
# ============================================================
def _as_dict(result):
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw": result}
    return {"raw": result}


def _short(data, limit: int = 160) -> str:
    text = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return text if len(text) <= limit else text[:limit] + "..."


# ============================================================
# 兼容旧接口（executor/views.py 使用）
# ============================================================
async def execute_ui_test(test_code: str, test_file: str):
    from apps.mcp.client import run_playwright_test

    return await run_playwright_test(test_code=test_code, test_file=test_file)


async def execute_api_test(method: str, url: str, **kwargs):
    from apps.mcp.client import run_api_test

    return await run_api_test(method, url, **kwargs)


async def query_database(sql: str, connection: str = "default"):
    from apps.mcp.client import query_database as _query

    return await _query(sql, connection)
