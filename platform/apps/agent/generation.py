"""
LLM 用例生成（Phase J Step 2）。

把 Scenario 转成三类用例：
- 手动用例（kind=manual）
- UI 自动化（kind=automated, test_type=ui）
- 接口自动化（kind=automated, test_type=api）

使用 call_llm + pydantic 校验 + 一次自动修复；结果去重。
"""
import json
import time
from pathlib import Path

from . import prompts
from .llm import call_llm
from .router import PRICING, route
from .schemas import SCHEMA_BY_KIND


# ============================================================
# 结构化调用
# ============================================================
def extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象（容忍 ```json 围栏/前后缀）。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1] if raw.count("```") >= 2 else raw
        raw = raw.lstrip("json").strip() if raw.lower().startswith("json") else raw
    try:
        return json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise


async def call_structured(config, prompt: str, schema, *, system: str = "", task: str = ""):
    """调用 LLM 并校验为 schema；失败时带错误信息重试一次。"""
    started = time.perf_counter()
    result = await call_llm(config, prompt, system=system)
    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = result.get("usage", {})
    try:
        return _validate(result["content"], schema), usage, latency_ms
    except Exception as exc:  # noqa: BLE001
        repair = (
            f"你上次的输出无法解析为规定 JSON：{exc}\n"
            f"请严格只输出合法 JSON。原始输出：\n{result['content']}"
        )
        result2 = await call_llm(config, repair, system=system)
        usage2 = result2.get("usage", {})
        merged = {
            "input_tokens": usage.get("input_tokens", 0) + usage2.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0) + usage2.get("output_tokens", 0),
        }
        latency_ms += int((time.perf_counter() - started) * 1000)
        return _validate(result2["content"], schema), merged, latency_ms


def _validate(content: str, schema):
    data = extract_json(content)
    return schema.model_validate(data)


# ============================================================
# 成本记录（best-effort，未配置 DB 时忽略）
# ============================================================
def _cost_usd(input_tokens: int, output_tokens: int) -> float:
    price = PRICING["flash"]
    return round(
        input_tokens / 1_000_000 * price["input"]
        + output_tokens / 1_000_000 * price["output"],
        6,
    )


async def record_llm_call(
    task: str,
    config,
    usage: dict,
    *,
    latency_ms: int = 0,
    success: bool = True,
    error: str = "",
    project_pk: int | None = None,
) -> None:
    """把一次调用写入 LLMCall（失败不阻断）。"""
    try:
        from asgiref.sync import sync_to_async
        from django.conf import settings

        if not settings.configured:
            return

        from apps.core.models import LLMCall

        def _create():
            LLMCall.objects.create(
                project_id=project_pk,
                task=task,
                model=config.model,
                reasoning=config.reasoning_effort or "low",
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                cost_usd=_cost_usd(
                    int(usage.get("input_tokens", 0) or 0),
                    int(usage.get("output_tokens", 0) or 0),
                ),
                latency_ms=latency_ms,
                success=success,
                error=error,
            )

        await sync_to_async(_create, thread_sensitive=False)()
    except Exception:  # noqa: BLE001 - 观测失败不影响生成
        return


# ============================================================
# 场景 → 用例
# ============================================================
def default_ui_target() -> str:
    fixture = (
        Path(__file__).resolve().parents[3]
        / "mcp_servers" / "fixtures" / "login.html"
    )
    return fixture.as_uri()


def resolve_automation(scenario: dict) -> dict:
    """决定生成哪些形态。旧 Markdown 场景无 automation 时按 type 推导。"""
    automation = dict(scenario.get("automation") or {})
    if automation:
        return {
            "manual": bool(automation.get("manual", False)),
            "ui": bool(automation.get("ui", False)),
            "api": bool(automation.get("api", False)),
        }
    primary = scenario.get("type", "ui")
    return {"manual": True, "ui": primary == "ui", "api": primary == "api"}


async def generate_for_scenario(
    scenario: dict,
    *,
    project_pk: int | None = None,
    api_base_url: str = "",
    ui_target_url: str = "",
    manual_count: int = 0,
) -> list[dict]:
    """按场景 automation 生成手动/UI/接口用例（去重后返回）。"""
    automation = resolve_automation(scenario)
    scenario_id = scenario.get("scenario_id")
    module = scenario.get("module", "")
    cases: list[dict] = []

    if automation["manual"]:
        cases += await _generate(
            "manual", scenario, prompts.build_manual_prompt(scenario),
            prompts.MANUAL_SYSTEM, project_pk, scenario_id, module,
        )
    if automation["ui"]:
        target = (
            ui_target_url
            or scenario.get("env", {}).get("ui")
            or default_ui_target()
        )
        cases += await _generate(
            "ui", scenario, prompts.build_ui_prompt(scenario, target),
            prompts.UI_SYSTEM, project_pk, scenario_id, module, ui_target=target,
        )
    if automation["api"]:
        if scenario.get("api"):
            cases += _api_cases_from_spec(scenario, api_base_url)
        else:
            base = api_base_url or scenario.get("env", {}).get("api", "")
            cases += await _generate(
                "api", scenario, prompts.build_api_prompt(scenario, base),
                prompts.API_SYSTEM, project_pk, scenario_id, module, api_base=base,
            )

    return dedup(cases)


def resolve_url(path: str, base: str) -> str:
    if not path:
        return path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if base:
        return base.rstrip("/") + (path if path.startswith("/") else f"/{path}")
    return path


def _api_cases_from_spec(scenario: dict, api_base_url: str = "") -> list[dict]:
    """Swagger 派生的确定性接口用例（不调用 LLM）。"""
    api = scenario.get("api") or {}
    base = api_base_url or scenario.get("env", {}).get("api", "")
    url = resolve_url(api.get("path", ""), base)
    assertions = api.get("assertions") or [
        {"type": "status_equals", "expected": api.get("expected_status", 200)}
    ]
    step = {
        "action": "request",
        "method": (api.get("method") or "GET").upper(),
        "url": url,
        "headers": api.get("headers") or {},
        "body": api.get("body") or {},
        "params": api.get("params") or {},
        "description": scenario.get("title", ""),
    }
    return [
        {
            "kind": "automated",
            "test_type": "api",
            "title": scenario.get("title", ""),
            "preconditions": [],
            "steps": [step],
            "assertions": assertions,
            "priority": scenario.get("priority", "P1"),
            "tags": list(dict.fromkeys(scenario.get("tags") or [])),
            "module": scenario.get("module", ""),
            "scenario_id": scenario.get("scenario_id"),
            "manual_steps": [],
            "expected_result": "",
            "target_url": url,
        }
    ]


async def _generate(
    kind: str,
    scenario: dict,
    prompt: str,
    system: str,
    project_pk: int | None,
    scenario_id: int | None,
    module: str,
    *,
    api_base: str = "",
    ui_target: str = "",
) -> list[dict]:
    task = {"manual": "generate_manual_cases", "ui": "generate_ui_tests", "api": "generate_api_tests"}[kind]
    config = route(task)
    schema = SCHEMA_BY_KIND[kind]
    structured, usage, latency_ms = await call_structured(
        config, prompt, schema, system=system, task=task
    )
    await record_llm_call(
        task, config, usage, latency_ms=latency_ms, project_pk=project_pk
    )
    return [
        _normalize(
            kind, case, scenario, scenario_id, module,
            api_base=api_base, ui_target=ui_target,
        )
        for case in structured.cases
    ]


def _normalize(
    kind: str,
    case,
    scenario: dict,
    scenario_id,
    module: str,
    *,
    api_base: str = "",
    ui_target: str = "",
) -> dict:
    priority = getattr(case, "priority", "P1") or scenario.get("priority", "P1")
    tags = list(getattr(case, "tags", []) or []) + list(scenario.get("tags", []) or [])
    tags = list(dict.fromkeys(tags))

    if kind == "manual":
        return {
            "kind": "manual",
            "test_type": "functional",
            "title": case.title,
            "preconditions": list(case.preconditions or []),
            "steps": [],
            "assertions": [],
            "priority": priority,
            "tags": tags,
            "module": module,
            "scenario_id": scenario_id,
            "manual_steps": [s.model_dump() for s in case.steps],
            "expected_result": case.expected_result,
            "target_url": "",
        }

    if kind == "ui":
        target = (
            case.target_url
            or ui_target
            or scenario.get("env", {}).get("ui")
            or default_ui_target()
        )
        steps = [s.model_dump() for s in case.steps]
        for step in steps:
            if (step.get("action") or "").lower() in ("goto", "navigate") and not step.get("value"):
                step["value"] = target
        return {
            "kind": "automated",
            "test_type": "ui",
            "title": case.title,
            "preconditions": list(case.preconditions or []),
            "steps": steps,
            "assertions": [a.model_dump() for a in case.assertions],
            "priority": priority,
            "tags": tags,
            "module": module,
            "scenario_id": scenario_id,
            "manual_steps": [],
            "expected_result": "",
            "target_url": target,
        }

    # api
    base = api_base or (scenario.get("env", {}) or {}).get("api", "")
    path = case.path or ""
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    elif base:
        url = base.rstrip("/") + (path if path.startswith("/") else f"/{path}")
    else:
        url = path
    step = {
        "action": "request",
        "method": (case.method or "GET").upper(),
        "url": url,
        "headers": case.headers or {},
        "body": case.body or {},
        "params": case.params or {},
        "description": case.title,
    }
    return {
        "kind": "automated",
        "test_type": "api",
        "title": case.title,
        "preconditions": [],
        "steps": [step],
        "assertions": [a.model_dump() for a in case.assertions],
        "priority": priority,
        "tags": tags,
        "module": module,
        "scenario_id": scenario_id,
        "manual_steps": [],
        "expected_result": "",
        "target_url": url,
    }


# ============================================================
# 去重
# ============================================================
def fingerprint(case: dict) -> str:
    payload = {
        "kind": case.get("kind"),
        "test_type": case.get("test_type"),
        "title": (case.get("title") or "").strip().lower(),
        "steps": case.get("steps") or case.get("manual_steps") or [],
        "assertions": case.get("assertions") or [],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def dedup(cases: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for case in cases:
        key = fingerprint(case)
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    return unique
