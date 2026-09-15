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
