"""
LangGraph 工作流编排

流程：
  START → retrieve → understand → design_scenarios → generate_steps
  → generate_assertions → generate_api_code → generate_ui_code
  → execute → [heal loop: self_heal → execute] → finalize → END
"""
from langgraph.graph import StateGraph, END
from .state import AgentState
from . import nodes
import json


def build_graph():
    """构建 LangGraph 状态图"""
    graph = StateGraph(AgentState)

    # ---- 添加节点 ----
    graph.add_node("retrieve", nodes.retrieve_node)
    graph.add_node("understand", nodes.understand_node)
    graph.add_node("design_scenarios", nodes.design_scenarios_node)
    graph.add_node("generate_steps", nodes.generate_steps_node)
    graph.add_node("generate_assertions", nodes.generate_assertions_node)
    graph.add_node("generate_api_code", nodes.generate_api_code_node)
    graph.add_node("generate_ui_code", nodes.generate_ui_code_node)
    graph.add_node("execute", nodes.execute_node)
    graph.add_node("self_heal", nodes.self_heal_node)
    graph.add_node("finalize", _finalize)

    # ---- 主流程边 ----
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "understand")
    graph.add_edge("understand", "design_scenarios")
    graph.add_edge("design_scenarios", "generate_steps")
    graph.add_edge("generate_steps", "generate_assertions")
    graph.add_edge("generate_assertions", "generate_api_code")
    graph.add_edge("generate_api_code", "generate_ui_code")
    graph.add_edge("generate_ui_code", "execute")

    # ---- 条件边：执行后是否自愈 ----
    graph.add_conditional_edges(
        "execute",
        nodes.should_heal,
        {"heal": "self_heal", "finalize": "finalize"},
    )

    # ---- 自愈后重新执行或结束 ----
    graph.add_conditional_edges(
        "self_heal",
        nodes.after_heal,
        {"execute": "execute", "finalize": "finalize"},
    )

    graph.add_edge("finalize", END)

    return graph.compile()


async def _finalize(state: AgentState) -> dict:
    """最终化处理：入库、生成报告"""
    status = state.get("final_status", "passed")
    return {"final_status": status}


# 单例（编译后的图可缓存）
_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


# ============================================================
# 便捷入口
# ============================================================
async def run_test_workflow(
    requirement: str,
    project_id: str = "",
    retry_budget: int = 3,
) -> dict:
    """
    运行完整测试工作流

    Usage:
        result = await run_test_workflow(
            requirement="用户登录功能，支持手机号+验证码",
            project_id="proj_123",
        )
    """
    graph = get_graph()
    initial_state: AgentState = {
        "requirement": requirement,
        "project_id": project_id,
        "heal_attempts": 0,
        "retry_budget": retry_budget,
        "test_cases": [],
        "execution_results": [],
        "healed_locators": [],
    }
    final_state = await graph.ainvoke(initial_state)
    return final_state


# ============================================================
# Phase C 最小闭环：planner → generator(MCP) → reporter(DB)
# ============================================================


async def planner_node(state: AgentState) -> dict:
    """把目标拆解为执行计划（确定性，不调用 LLM），并检索历史相似用例。"""
    goal = state["requirement"]
    project_id = state.get("project_id") or "demo"

    # Phase G：生成前先检索历史相似用例作为 few-shot
    from apps.rag.retriever import aretrieve_similar_cases

    cases = await aretrieve_similar_cases(goal, top_k=3, project_id=project_id)

    plan = [
        f"1. 解析目标: {goal}",
        f"2. RAG 检索历史相似用例: [retrieved {len(cases)} similar cases]",
        "3. 通过 MCP(stdio) 调用 fake_generate_test 生成用例（注入历史 selector few-shot）",
        "4. 将用例写入 PostgreSQL TestCase 表",
    ]
    return {"plan": plan, "retrieved_cases": cases}


def _few_shot_payload(retrieved: list[dict]) -> str:
    """把检索到的历史用例压缩为 few-shot JSON（title + steps）。"""
    shots = []
    for item in retrieved or []:
        payload = item.get("payload", {}) if isinstance(item, dict) else {}
        shots.append(
            {
                "title": payload.get("title", ""),
                "steps": payload.get("steps", []),
            }
        )
    return json.dumps(shots, ensure_ascii=False) if shots else ""


def _login_fixture_url() -> str:
    """本地登录示例页（file://），供确定性 UI 用例执行。"""
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parents[3]
        / "mcp_servers" / "fixtures" / "login.html"
    )
    return fixture.as_uri()


async def generator_node(state: AgentState) -> dict:
    """按场景类型生成用例：UI → Playwright steps；API → api_server MCP。"""
    if state.get("case_type") == "api":
        test_cases = await _generate_api_cases(state)
    else:
        test_cases = await _generate_ui_cases(state)
    return {
        "test_cases": test_cases,
        "few_shot_used": len(state.get("retrieved_cases", [])),
    }


async def _generate_ui_cases(state: AgentState) -> list[dict]:
    """UI 场景：优先使用文档显式 steps，否则回退 echo MCP 生成。"""
    from apps.mcp.client import MCPClient

    scenario = state.get("scenario") or {}
    spec = scenario.get("spec") or {}
    if spec.get("type") == "ui" or spec.get("steps"):
        target_url = spec.get("target_url") or _login_fixture_url()
        steps = [dict(step) for step in spec.get("steps", [])]
        for step in steps:
            if (step.get("action") or "").lower() in ("goto", "navigate") and not step.get("value"):
                step["value"] = target_url
        return [
            {
                "title": scenario.get("title") or state["requirement"],
                "preconditions": scenario.get("acceptance_criteria", []),
                "steps": steps,
                "assertions": spec.get("assertions", []),
                "priority": scenario.get("priority", "P1"),
                "tags": scenario.get("tags") or ["ui"],
                "target_url": target_url,
            }
        ]

    goal = state["requirement"]
    count = int(state.get("case_count", 3))
    few_shot = _few_shot_payload(state.get("retrieved_cases", []))
    async with MCPClient(servers=["echo"]) as mcp:
        raw = await mcp.call_tool(
            "echo",
            "fake_generate_test",
            {"goal": goal, "count": count, "few_shot": few_shot},
        )
    return json.loads(raw) if isinstance(raw, str) else raw


async def _generate_api_cases(state: AgentState) -> list[dict]:
    """API 场景：构造 request steps + assertions，并经 api_server MCP 探测。"""
    from apps.mcp.client import MCPClient

    scenario = state.get("scenario") or {}
    api = scenario.get("api") or {}
    method = (api.get("method") or "GET").upper()
    path = api.get("path") or ""
    base_url = state.get("api_base_url") or ""
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    elif base_url:
        url = base_url.rstrip("/") + (path if path.startswith("/") else f"/{path}")
    else:
        url = path

    headers = api.get("headers") or {}
    body = api.get("body") or {}
    params = api.get("params") or {}
    assertions = api.get("assertions") or [
        {"type": "status_equals", "expected": api.get("expected_status", 200)}
    ]

    # Phase I：生成阶段经 api_server MCP 探测接口（失败不阻断）
    baseline = {}
    if url:
        try:
            async with MCPClient(servers=["api"]) as mcp:
                raw = await mcp.call_tool(
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
            baseline = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:  # noqa: BLE001
            baseline = {"error": f"{type(exc).__name__}: {exc}"}

    step = {
        "action": "request",
        "method": method,
        "url": url,
        "headers": headers,
        "body": body,
        "params": params,
        "description": scenario.get("title") or state["requirement"],
    }
    return [
        {
            "title": scenario.get("title") or state["requirement"],
            "preconditions": scenario.get("acceptance_criteria", []),
            "steps": [step],
            "assertions": assertions,
            "priority": scenario.get("priority", "P1"),
            "tags": scenario.get("tags") or ["api"],
            "target_url": url,
            "api_baseline": baseline,
        }
    ]


def _save_test_cases(
    project_id: str,
    test_cases: list[dict],
    source: str,
    project_ref_pk: int | None = None,
) -> list[int]:
    """同步写入 TestCase（由 sync_to_async 包装，避免 async ORM 限制）。"""
    from apps.testcases.models import TestCase

    project = None
    if project_ref_pk:
        from apps.core.models import Project

        project = Project.objects.filter(pk=project_ref_pk).first()

    saved_ids: list[int] = []
    for case in test_cases:
        steps = case.get("steps", [])
        obj = TestCase.objects.create(
            project=project,
            project_key=project_id,
            title=case["title"],
            preconditions=case.get("preconditions", []),
            steps=steps,
            assertions=case.get("assertions", []),
            priority=case.get("priority", TestCase.Priority.P1),
            tags=case.get("tags", []),
            source=source,
            target_url=case.get("target_url", ""),
            raw_steps=steps,
        )
        saved_ids.append(obj.id)
    return saved_ids


async def reporter_node(state: AgentState) -> dict:
    """把生成的用例写入数据库，返回新增主键。"""
    from asgiref.sync import sync_to_async

    project_id = state.get("project_id") or "demo"
    test_cases = state.get("test_cases", [])
    saved_ids = await sync_to_async(_save_test_cases)(
        project_id,
        test_cases,
        state.get("source") or "agent:run_agent_demo",
        state.get("project_ref_pk"),
    )
    return {
        "saved_ids": saved_ids,
        "final_status": "passed",
    }


async def executor_node(state: AgentState) -> dict:
    """可选：对 reporter 入库的用例真执行（Playwright MCP），写批次/步骤明细+报告。"""
    if not state.get("execute"):
        return {}

    from apps.executor.executor import execute_cases

    batch = await execute_cases(
        state.get("saved_ids", []),
        goal=state.get("requirement", ""),
        source="agent:run_agent_demo",
        project_id=state.get("project_id") or "demo",
    )
    return {
        "execution_results": batch["results"],
        "execution_run_id": batch["run_id"],
        "execution_report": batch.get("report", {}),
    }


def _inject_failure(case: dict, mode: str) -> None:
    """演示用：人为把一条用例改造成必败，触发对应自愈规则。"""
    if mode == "selector":
        for step in case.get("steps", []):
            if step.get("action") == "fill" and step.get("selector") == "#code":
                step["selector"] = "#code_old"
    elif mode == "assertion":
        for assertion in case.get("assertions", []):
            if assertion.get("selector") == "#result":
                assertion["expected"] = "登录OK"
    elif mode == "timing":
        for step in case.get("steps", []):
            if step.get("action") == "click" and step.get("selector") == "#submit":
                step["selector"] = "#slow-submit"


async def inject_failure_node(state: AgentState) -> dict:
    """可选：故意注入失败（--inject-failure）供自愈演示。"""
    mode = state.get("inject_failure") or "none"
    if mode == "none":
        return {}
    cases = list(state.get("test_cases", []))
    if cases:
        _inject_failure(cases[0], mode)
    return {"test_cases": cases}


async def healer_node(state: AgentState) -> dict:
    """可选：对执行失败的用例自动自愈（分析→修复→重跑→沉淀）。"""
    if not (state.get("execute") and state.get("self_heal")):
        return {}

    from apps.selfheal.engine import run as run_selfheal

    failed_cases = [
        r["case_id"]
        for r in state.get("execution_results", [])
        if r.get("status") in ("fail", "error")
    ]
    heal_results = [await run_selfheal(case_id) for case_id in failed_cases]
    return {"heal_results": heal_results}


def build_demo_graph():
    """构建 Phase F 闭环：planner → generator → injector → reporter → executor → healer。"""
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("generator", generator_node)
    graph.add_node("injector", inject_failure_node)
    graph.add_node("reporter", reporter_node)
    graph.add_node("executor", executor_node)
    graph.add_node("healer", healer_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "generator")
    graph.add_edge("generator", "injector")
    graph.add_edge("injector", "reporter")
    graph.add_edge("reporter", "executor")
    graph.add_edge("executor", "healer")
    graph.add_edge("healer", END)

    return graph.compile()


_demo_graph = None


def get_demo_graph():
    global _demo_graph
    if _demo_graph is None:
        _demo_graph = build_demo_graph()
    return _demo_graph


# ============================================================
# Phase I：生成图（planner → generator → reporter，仅生成）
# ============================================================
def build_generation_graph():
    """仅生成不含执行的图：planner → generator → reporter。"""
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("generator", generator_node)
    graph.add_node("reporter", reporter_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "generator")
    graph.add_edge("generator", "reporter")
    graph.add_edge("reporter", END)

    return graph.compile()


_generation_graph = None


def get_generation_graph():
    global _generation_graph
    if _generation_graph is None:
        _generation_graph = build_generation_graph()
    return _generation_graph


# ============================================================
# Phase I：完整图（planner → generator → reporter → executor[含自愈]）
# ============================================================
async def full_executor_node(state: AgentState) -> dict:
    """执行 reporter 入库用例，并默认自动自愈失败用例（无需 flag）。"""
    from apps.executor.executor import execute_cases

    case_ids = state.get("saved_ids", [])
    if not case_ids:
        return {"execution_results": [], "heal_results": []}

    batch = await execute_cases(
        case_ids,
        goal=state.get("requirement", ""),
        source=state.get("source") or "agent:full",
        project_id=state.get("project_id") or "demo",
        auto_heal=True,
    )
    return {
        "execution_results": batch["results"],
        "execution_run_id": batch["run_id"],
        "execution_report": batch.get("report", {}),
        "heal_results": batch.get("heal_results", []),
    }


def build_full_graph():
    """默认串联执行+自愈：planner → generator → reporter → executor[heal]。"""
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("generator", generator_node)
    graph.add_node("reporter", reporter_node)
    graph.add_node("executor", full_executor_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "generator")
    graph.add_edge("generator", "reporter")
    graph.add_edge("reporter", "executor")
    graph.add_edge("executor", END)

    return graph.compile()


_full_graph = None


def get_full_graph():
    global _full_graph
    if _full_graph is None:
        _full_graph = build_full_graph()
    return _full_graph


async def run_full_workflow(
    requirement: str,
    project_id: str = "demo",
    case_count: int = 3,
    *,
    project_ref_pk: int | None = None,
    case_type: str = "ui",
    scenario: dict | None = None,
    api_base_url: str = "",
    source: str = "agent:full",
) -> dict:
    """一键运行 生成 → 执行 → 自愈 全链路。"""
    initial_state: AgentState = {
        "requirement": requirement,
        "project_id": project_id,
        "case_count": case_count,
        "project_ref_pk": project_ref_pk,
        "case_type": case_type,
        "scenario": scenario or {},
        "api_base_url": api_base_url,
        "source": source,
        "test_cases": [],
        "retrieved_cases": [],
    }
    return await get_full_graph().ainvoke(initial_state)


async def run_agent_demo_workflow(
    goal: str,
    project_id: str = "demo",
    count: int = 3,
    execute: bool = False,
    self_heal: bool = False,
    inject_failure: str = "none",
) -> dict:
    """
    运行 Phase F 最小闭环：
    planner → generator(MCP) → injector → reporter(DB) → executor → healer

    Usage:
        result = await run_agent_demo_workflow("登录", "demo", execute=True, self_heal=True)
    """
    graph = get_demo_graph()
    initial_state: AgentState = {
        "requirement": goal,
        "project_id": project_id,
        "case_count": count,
        "test_cases": [],
        "execute": execute,
        "self_heal": self_heal,
        "inject_failure": inject_failure,
    }
    return await graph.ainvoke(initial_state)
