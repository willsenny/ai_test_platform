"""
规则修复器（Phase F · 规则驱动）

按 failure_type 选择修复策略：
- element_not_found → selector_remap     : snapshot 枚举元素，模糊匹配找新 selector
- text_mismatch     → assertion_refresh  : get_text 取当前值，更新断言 expected
- timeout           → timing_wait        : 在失败步前插入 wait 步骤

修复直接改写 TestCase.raw_steps / steps / assertions 并落库。
"""
import json
import re
from dataclasses import dataclass

from asgiref.sync import sync_to_async


@dataclass
class FixResult:
    success: bool
    strategy: str
    old_value: str
    new_value: str
    detail: str = ""
    # Phase G：命中历史成功修复经验时的提示
    rag_hint: str = ""


# 历史策略 → 失败类型（用于未知失败的兜底）
_STRATEGY_TO_TYPE = {
    "selector_remap": "element_not_found",
    "assertion_refresh": "text_mismatch",
    "timing_wait": "timeout",
}


def _heal_experience(pattern: str) -> tuple[str, str | None]:
    """检索 heal_logs；返回 (hint_text, 可映射的 failure_type)。"""
    try:
        from apps.rag.retriever import retrieve_heal_experience

        hits = retrieve_heal_experience(pattern, top_k=3, only_successful=True)
    except Exception:  # noqa: BLE001
        return "", None
    if not hits:
        return "", None
    top = hits[0].get("payload", {})
    strategy = top.get("fix_strategy", "")
    rate = top.get("success_rate", 0.0)
    hint = f"history: {top.get('failure_pattern', pattern)} -> {strategy} (success_rate={rate})"
    return hint, _STRATEGY_TO_TYPE.get(strategy)


async def apply_fix(case_id: int, feature) -> FixResult:
    from apps.testcases.models import TestCase

    case = await sync_to_async(TestCase.objects.get)(pk=case_id)

    rag_hint, mapped_type = _heal_experience(feature.failure_type)
    effective = feature.failure_type
    if effective not in ("element_not_found", "text_mismatch", "timeout", "navigation_failed") and mapped_type:
        effective = mapped_type

    if effective == "element_not_found":
        result = await _fix_selector(case, feature)
    elif effective == "text_mismatch":
        result = await _fix_assertion(case, feature)
    elif effective == "timeout":
        result = await _fix_timing(case, feature)
    elif effective == "navigation_failed":
        result = FixResult(
            False, "url_refresh", feature.value, "", "navigation fix not enabled (no target)"
        )
    else:
        result = FixResult(False, "none", feature.selector, "", "no rule matched")

    result.rag_hint = rag_hint
    if result.success:
        await sync_to_async(case.save)(update_fields=["raw_steps", "steps", "assertions"])
    return result


# ============================================================
# element_not_found → 重定位 selector
# ============================================================
async def _fix_selector(case, feature) -> FixResult:
    from apps.mcp.client import MCPClient

    async with MCPClient(servers=["playwright"]) as mcp:
        if case.target_url:
            await mcp.call_tool("playwright", "navigate", {"url": case.target_url})
        snap = _as_dict(await mcp.call_tool("playwright", "snapshot"))

    if snap.get("error"):
        return FixResult(False, "selector_remap", feature.selector, "", snap["error"])

    elements = snap.get("elements", [])
    hint = _tokens(feature.selector)
    best, score = _best_match(elements, hint)
    if best is None or score < 1:
        return FixResult(
            False, "selector_remap", feature.selector, "", "no candidate element matched"
        )

    new_selector = _selector_for(best)
    if not new_selector:
        return FixResult(False, "selector_remap", feature.selector, "", "candidate has no usable attr")
    if new_selector == feature.selector:
        return FixResult(
            False, "selector_remap", feature.selector, new_selector,
            "best candidate equals original selector (not a selector fault)",
        )

    changed = _replace_selector(case, feature.selector, new_selector)
    return FixResult(
        bool(changed),
        "selector_remap",
        feature.selector,
        new_selector,
        f"fuzzy match score={score} element={best.get('id') or best.get('name') or best.get('tag')}",
    )


# ============================================================
# text_mismatch → 刷新断言 expected
# ============================================================
async def _fix_assertion(case, feature) -> FixResult:
    from apps.mcp.client import MCPClient

    async with MCPClient(servers=["playwright"]) as mcp:
        if case.target_url:
            await mcp.call_tool("playwright", "navigate", {"url": case.target_url})
        await _replay_steps(case, mcp)
        res = _as_dict(
            await mcp.call_tool("playwright", "get_text", {"selector": feature.selector})
        )

    if res.get("error"):
        return FixResult(False, "assertion_refresh", feature.expected, "", res["error"])

    actual = str(res.get("text", "")).strip()
    if not actual:
        return FixResult(
            False, "assertion_refresh", feature.expected, "", "current text is empty"
        )

    changed = _update_assertion(case, feature.selector, feature.expected, actual)
    return FixResult(
        bool(changed),
        "assertion_refresh",
        feature.expected,
        actual,
        f"observed current text for {feature.selector}",
    )


# ============================================================
# timeout → 插入 wait
# ============================================================
async def _fix_timing(case, feature) -> FixResult:
    changed = _insert_wait_before(case, feature, wait_ms=3500)
    return FixResult(
        bool(changed),
        "timing_wait",
        "",
        "3500",
        f"inserted wait before {feature.action} {feature.selector}",
    )


# ============================================================
# Case 变更
# ============================================================
def _replace_selector(case, old: str, new: str) -> bool:
    changed = False
    for field in ("raw_steps", "steps"):
        steps = list(getattr(case, field) or [])
        field_changed = False
        for step in steps:
            if step.get("selector") == old:
                step["selector"] = new
                field_changed = True
        if field_changed:
            setattr(case, field, steps)
            changed = True
    return changed


def _update_assertion(case, selector: str, old_expected: str, new_expected: str) -> bool:
    assertions = list(case.assertions or [])
    changed = False
    for assertion in assertions:
        if assertion.get("selector") == selector and assertion.get("expected") == old_expected:
            assertion["expected"] = new_expected
            changed = True

    if changed:
        for field in ("raw_steps", "steps"):
            steps = list(getattr(case, field) or [])
            field_changed = False
            for step in steps:
                if (
                    step.get("action") == "assert_text"
                    and step.get("selector") == selector
                    and step.get("value") == old_expected
                ):
                    step["value"] = new_expected
                    field_changed = True
            if field_changed:
                setattr(case, field, steps)
        case.assertions = assertions

    return changed


def _insert_wait_before(case, feature, wait_ms: int = 3500) -> bool:
    changed = False
    for field in ("raw_steps", "steps"):
        steps = list(getattr(case, field) or [])
        out = []
        field_changed = False
        for step in steps:
            if (
                step.get("selector") == feature.selector
                and (step.get("action") or "") == feature.action
            ):
                out.append(
                    {
                        "action": "wait",
                        "selector": "",
                        "value": str(wait_ms),
                        "description": "self-heal timing wait",
                    }
                )
                field_changed = True
            out.append(step)
        if field_changed:
            setattr(case, field, out)
            changed = True
    return changed


# ============================================================
# 匹配工具
# ============================================================
def _tokens(value: str) -> set[str]:
    text = (value or "").lower()
    text = re.sub(r"[#\[\]\.'\"=@:$]", " ", text)
    return {t for t in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", text) if t}


def _best_match(elements: list[dict], hint: set[str]) -> tuple[dict | None, float]:
    best = None
    best_score = 0.0
    for el in elements:
        haystack = " ".join(
            str(el.get(k) or "")
            for k in ("id", "name", "placeholder", "ariaLabel", "text", "label")
        )
        score = float(len(hint & _tokens(haystack)))
        if el.get("id") and (hint & _tokens(str(el["id"]))):
            score += 0.5
        if score > best_score:
            best_score = score
            best = el
    return best, best_score


def _selector_for(el: dict) -> str:
    if el.get("id"):
        return f"#{el['id']}"
    if el.get("name"):
        return f'[name="{el["name"]}"]'
    if el.get("placeholder"):
        return f'[placeholder="{el["placeholder"]}"]'
    if el.get("text"):
        return f"text={str(el['text'])[:40]}"
    return ""


async def _replay_steps(case, mcp) -> None:
    """在修复断言前，回放页面步骤到断言前状态（忽略中间错误）。"""
    steps = list(case.raw_steps or case.steps or [])
    for step in steps:
        action = (step.get("action") or "").strip()
        selector = step.get("selector", "") or ""
        value = step.get("value", "") or ""
        try:
            if action in ("goto", "navigate"):
                await mcp.call_tool("playwright", "navigate", {"url": value or case.target_url})
            elif action == "fill":
                await mcp.call_tool("playwright", "fill", {"selector": selector, "value": value})
            elif action == "click":
                await mcp.call_tool("playwright", "click", {"selector": selector})
        except Exception:
            continue


def _as_dict(result) -> dict:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw": result}
    return {"raw": result}
