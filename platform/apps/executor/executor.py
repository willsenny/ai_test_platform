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
import re
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
        run = await sync_to_async(_create_run)(case.project_key, case.title, "executor:single", 1)
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
    auto_heal: bool = False,
) -> dict:
    """一个批次执行多条用例，统一生成 TestRun + 报告。

    auto_heal=True 时，对存在 fail/error 的用例自动触发规则自愈（Phase I 默认串联）。
    """
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
            "heal_results": [],
            "healed": 0,
        }

    if not project_id:
        first = await sync_to_async(_load_case)(case_ids[0])
        project_id = first.project_key

    run = await sync_to_async(_create_run)(project_id, goal, source, len(case_ids))
    results = [await execute_case(cid, run_id=run.pk) for cid in case_ids]

    await sync_to_async(_finalize_run)(run.pk, results)
    run_obj = await sync_to_async(_load_run)(run.pk)
    paths = await sync_to_async(_write_report)(run_obj)
    await sync_to_async(_save_report_paths)(run.pk, paths["json"], paths["html"])

    passed = sum(1 for r in results if r["status"] == "pass")
    output = {
        "run_id": run.pk,
        "status": run_obj.status,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
        "report": paths,
        "heal_results": [],
        "healed": 0,
    }

    if auto_heal:
        heal_results = await _auto_heal(results, run.pk)
        output["heal_results"] = heal_results
        output["healed"] = sum(1 for h in heal_results if h.get("healed"))

    return output


async def _auto_heal(results: list[dict], run_id: int) -> list[dict]:
    """执行后自动自愈失败用例（Phase I）。"""
    from apps.selfheal.engine import run as run_selfheal

    failed = [r for r in results if r["status"] in ("fail", "error")]
    heal_results = []
    for result in failed:
        step_ids = await sync_to_async(_failed_step_ids)(result["case_id"], run_id)
        try:
            heal = await run_selfheal(result["case_id"], step_ids)
        except Exception as exc:  # noqa: BLE001 - 自愈异常不阻断批次
            heal = {
                "case_id": result["case_id"],
                "healed": False,
                "failure_count": 0,
                "attempts": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        heal_results.append(heal)
    return heal_results


def _failed_step_ids(case_id: int, run_id: int) -> list[int]:
    from .models import TestStepResult

    return list(
        TestStepResult.objects.filter(
            run_id=run_id, testcase_id=case_id, status__in=["fail", "error"]
        ).values_list("pk", flat=True)
    )


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

    is_api = any(
        str(step.get("action") or "").lower() in ("request", "api_request")
        for step in steps
    )
    is_manual = getattr(case, "kind", "automated") == "manual"

    if is_manual:
        status = "skipped"
        log_lines.append("manual case skipped (not auto-executable)")
    elif not steps:
        status = "skipped"
        log_lines.append("no steps to execute")
    elif is_api:
        try:
            status = await _run_api_case(
                case, run_id, steps, assertions, rows, log_lines
            )
        except Exception as exc:
            status = "error"
            log_lines.append(f"api execution exception: {type(exc).__name__}: {exc}")
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


async def _run_api_case(
    case, run_id: int, steps: list[dict], assertions: list[dict],
    rows: list[dict], log_lines: list[str],
) -> str:
    """API 用例执行：经 api_server MCP 发请求，再本地校验断言。"""
    from apps.mcp.client import MCPClient

    responses: list[dict] = []
    async with MCPClient(servers=["api"]) as mcp:
        for idx, step in enumerate(steps, 1):
            action = str(step.get("action") or "").lower()
            if action not in ("request", "api_request"):
                rows.append(_step_row(
                    case.pk, run_id, idx, "step", action, "", "", "", "",
                    "skip", f"unknown api action '{action}'", 0,
                ))
                log_lines.append(f"[api step {idx}] SKIP unknown action '{action}'")
                continue

            method = (step.get("method") or "GET").upper()
            url = step.get("url") or case.target_url
            headers = step.get("headers") or {}
            body = step.get("body") or step.get("json") or {}
            params = step.get("params") or {}

            started = time.perf_counter()
            error = ""
            data: dict = {}
            try:
                result = await mcp.call_tool(
                    "api",
                    "send_request",
                    {
                        "method": method,
                        "url": url,
                        "headers": headers,
                        "json": body,
                        "params": params,
                    },
                )
                data = _as_dict(result)
                if isinstance(data, dict) and data.get("error"):
                    error = str(data["error"])
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            duration_ms = int((time.perf_counter() - started) * 1000)
            status_code = data.get("status_code") if isinstance(data, dict) else None
            actual = _short({"status_code": status_code, "body": data.get("body")})
            rows.append(_step_row(
                case.pk, run_id, idx, "step", f"request {method}", url,
                _short(body), "", actual, "error" if error else "pass", error, duration_ms,
            ))
            log_lines.append(
                f"[api step {idx}] {method} {url} -> "
                f"{error or f'status={status_code}'}"
            )
            responses.append(data if isinstance(data, dict) else {})
            if error:
                return "error"

    return _run_api_assertions(case, run_id, assertions, responses, rows, log_lines, len(steps))


def _run_api_assertions(
    case, run_id: int, assertions: list[dict], responses: list[dict],
    rows: list[dict], log_lines: list[str], step_offset: int,
) -> str:
    if not assertions:
        log_lines.append("[api assert] no assertions, treated as pass")
        return "pass"

    outcome = "pass"
    first = responses[0] if responses else {}
    for idx, assertion in enumerate(assertions, 1):
        a_type = assertion.get("type", "status_equals")
        expected = assertion.get("expected")
        row_index = step_offset + idx
        passed = False
        actual = ""
        error = ""

        if a_type == "status_equals":
            actual = first.get("status_code")
            passed = actual == expected or str(actual) == str(expected)
        elif a_type in ("json_field", "json_equals"):
            path = assertion.get("path", "")
            actual = _json_path_get(first.get("body"), path)
            passed = actual == expected or str(actual) == str(expected)
        elif a_type == "json_contains":
            path = assertion.get("path", "")
            actual = _json_path_get(first.get("body"), path)
            passed = str(expected) in str(actual)
        elif a_type == "json_path_exists":
            path = assertion.get("path", "")
            actual = _json_path_get(first.get("body"), path)
            passed = actual is not None
        elif a_type == "json_schema":
            schema = assertion.get("schema") or {}
            actual = _short(first.get("body"))
            try:
                import jsonschema

                jsonschema.validate(instance=first.get("body"), schema=schema)
                passed = True
            except Exception as exc:  # noqa: BLE001
                passed = False
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
        else:
            rows.append(_step_row(
                case.pk, run_id, row_index, "assert", a_type, "", "", "",
                "", "skip", f"unknown assertion type '{a_type}'", 0,
            ))
            log_lines.append(f"[api assert {idx}] SKIP unknown type '{a_type}'")
            continue

        step_status = "pass" if passed else "fail"
        if not passed and outcome != "error":
            outcome = "fail"
        rows.append(_step_row(
            case.pk, run_id, row_index, "assert", a_type, "", "",
            str(expected), str(actual), step_status, error, 0,
        ))
        log_lines.append(
            f"[api assert {idx}] {a_type} expected={expected!r} "
            f"actual={actual!r} -> {step_status}"
        )
    return outcome


def _json_path_get(obj, path: str):
    """简易 JSON 路径取值：支持 a.b.c / $.a.b / a[0]。"""
    if obj is None or not path:
        return None
    tokens = [t for t in re.split(r"\.|\[|\]|\$|'", str(path)) if t]
    current = obj
    for token in tokens:
        if isinstance(current, dict):
            current = current.get(token)
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


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
