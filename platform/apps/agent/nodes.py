"""
LangGraph 各节点实现

节点流程：
  retrieve → understand → design_scenarios → generate_steps
  → generate_assertions → generate_api_code → generate_ui_code
  → execute → [heal loop] → finalize
"""
import json
from .router import route, ModelTier, get_cost_tracker
from .state import AgentState, TestCase


# ============================================================
# Phase 1: RAG 检索
# ============================================================
async def retrieve_node(state: AgentState) -> dict:
    """从 Qdrant 检索需求文档、历史用例、接口规范、业务规则"""
    from apps.rag.service import retrieve
    query = state["requirement"]
    results = await retrieve(
        query=query,
        project_id=state.get("project_id", ""),
        top_k=10,
    )
    return {"retrieved_context": results}


# ============================================================
# Phase 2: 需求理解（L2 Pro - 需要推理）
# ============================================================
async def understand_node(state: AgentState) -> dict:
    """理解需求，提取实体、规则、边界条件"""
    cfg = route("design_workflow")  # → L2 Pro
    # 实际调用: await litellm.acompletion(model=cfg.model, ...)
    prompt = f"""
基于以下需求和相关知识，提取：
1. 核心业务实体
2. 业务规则和约束
3. 正常/异常场景边界
4. 需要重点验证的数据字段

需求: {state['requirement']}
相关知识: {json.dumps(state.get('retrieved_context', [])[:5], ensure_ascii=False)}
"""
    # response = await call_llm(cfg, prompt)
    response = {"content": ""}  # TODO: 接入实际 LLM 调用
    return {"_understanding": response["content"]}


# ============================================================
# Phase 3: 场景设计（L1 Flash - 批量）
# ============================================================
async def design_scenarios_node(state: AgentState) -> dict:
    """设计测试场景（等价类、边界值、异常流）"""
    cfg = route("generate_testcase")  # → L1 Flash
    # response = await call_llm(cfg, ...)
    scenarios = []  # TODO: 从 LLM 响应解析
    return {"scenarios": scenarios}


# ============================================================
# Phase 4: 步骤生成（L1 Flash）
# ============================================================
async def generate_steps_node(state: AgentState) -> dict:
    """为每个场景生成具体操作步骤"""
    cfg = route("generate_steps")  # → L1 Flash
    test_cases: list[TestCase] = []
    # response = await call_llm(cfg, structured_output=TestCase schema)
    return {"test_cases": test_cases}


# ============================================================
# Phase 5: 断言设计（L1 Flash）
# ============================================================
async def generate_assertions_node(state: AgentState) -> dict:
    """为每步生成断言（状态码、字段校验、数据库一致性）"""
    cfg = route("generate_assertion")  # → L1 Flash
    # response = await call_llm(cfg, ...)
    return {"test_cases": state.get("test_cases", [])}


# ============================================================
# Phase 6: API 自动化代码（L2 Pro - 多文件）
# ============================================================
async def generate_api_code_node(state: AgentState) -> dict:
    """生成 pytest + httpx 接口测试代码"""
    cfg = route("generate_api_tests")  # → L2 Pro
    template = '''
import pytest
import httpx

@pytest.mark.asyncio
async def test_{func_name}(client: httpx.AsyncClient):
    """{case_title}"""
    # Arrange
{arrange}

    # Act
    response = await client.{method}("{path}", json={body})

    # Assert
{assertions}
'''
    # response = await call_llm(cfg, template + context)
    return {"api_test_code": ""}  # TODO


# ============================================================
# Phase 7: UI 自动化代码（L2 Pro）
# ============================================================
async def generate_ui_code_node(state: AgentState) -> dict:
    """生成 Playwright 测试代码（基于 accessibility snapshot）"""
    cfg = route("generate_api_tests")  # → L2 Pro
    template = '''
import pytest
from playwright.async_api import Page

@pytest.mark.asyncio
async def test_{func_name}(page: Page):
    """{case_title}"""
    # 无需视觉模型 - 使用 accessibility snapshot
{snapshot_based_steps}
'''
    # response = await call_llm(cfg, template + context)
    return {"ui_test_code": ""}  # TODO


# ============================================================
# Phase 8: 执行（通过 MCP 调用 Playwright / API）
# ============================================================
async def execute_node(state: AgentState) -> dict:
    """通过 MCP 执行生成的测试代码"""
    from apps.mcp.client import call_tool
    results = []
    # 1. 写测试文件到临时目录
    # 2. 通过 MCP 触发 pytest 执行
    # result = await call_tool("playwright", "run_tests", {...})
    return {"execution_results": results}


# ============================================================
# Phase 9: 自愈检查（L3 Sonnet - 仅在失败时）
# ============================================================
async def self_heal_node(state: AgentState) -> dict:
    """
    自愈五段闭环：
    1. 规则修复 (L1) - 超时重试、等待条件
    2. 向量定位器库 (L1) - 相似元素匹配
    3. LLM 候选生成 (L3) - 分析失败截图/日志
    4. 重跑验证 (MCP) - 执行修复后代码
    5. 开 PR (Git MCP) - 自动提交修复
    """
    if state.get("heal_attempts", 0) >= state.get("retry_budget", 3):
        return {"final_status": "failed"}

    failures = [r for r in state.get("execution_results", [])
                if not r.get("passed")]

    healed = []
    for failure in failures:
        # Step 1: 规则修复 (L1 Flash)
        rule_fix = await _try_rule_based_fix(failure)
        if rule_fix:
            healed.append(rule_fix)
            continue

        # Step 2: 向量定位器库 (L1 Flash)
        locator = await _find_similar_locator(failure)
        if locator:
            healed.append(locator)
            continue

        # Step 3: LLM 候选 (L3 Sonnet - 仅此步用强模型)
        cfg = route("self_heal_repair")
        # response = await call_llm(cfg, failure_log + screenshot)
        candidate = {"old": failure.get("locator"), "new": "", "confidence": 0.0}

        # Step 4: 重跑验证 (MCP)
        verified = await _verify_fix(candidate, failure)
        if verified:
            healed.append(candidate)
            # Step 5: 开 PR (Git MCP)
            await _create_pr(candidate)

    return {
        "heal_attempts": state.get("heal_attempts", 0) + 1,
        "healed_locators": healed,
        "final_status": "healed" if healed else "failed",
    }


async def _try_rule_based_fix(failure: dict) -> dict | None:
    """规则修复：超时→增加等待、网络抖动→重试"""
    cfg = route("refine_locator")  # L1 Flash
    # 实现常见规则匹配
    return None  # TODO


async def _find_similar_locator(failure: dict) -> dict | None:
    """从向量定位器库查找相似元素"""
    cfg = route("refine_locator")  # L1 Flash
    # 从 Qdrant 检索历史成功的定位器
    return None  # TODO


async def _verify_fix(candidate: dict, failure: dict) -> bool:
    """通过 MCP 重跑验证修复"""
    from apps.mcp.client import call_tool
    # result = await call_tool("playwright", "run_single", {...})
    return True  # TODO


async def _create_pr(candidate: dict) -> None:
    """自动开 PR 提交修复的定位器"""
    from apps.mcp.client import call_tool
    # await call_tool("git", "create_pr", {...})
    pass


# ============================================================
# 条件边：是否进入自愈
# ============================================================
def should_heal(state: AgentState) -> str:
    results = state.get("execution_results", [])
    has_failure = any(not r.get("passed") for r in results)
    attempts = state.get("heal_attempts", 0)
    budget = state.get("retry_budget", 3)
    if has_failure and attempts < budget:
        return "heal"
    return "finalize"


def after_heal(state: AgentState) -> str:
    """自愈后重新执行"""
    if state.get("final_status") == "healed":
        return "execute"
    return "finalize"
