"""
LangGraph 状态定义：需求 → 场景 → 步骤 → 断言 → 代码 → 执行 → 自愈
"""
from typing import TypedDict, Annotated, Optional
from langgraph.graph import END
import operator


class TestCase(TypedDict):
    """结构化测试用例（Pydantic 校验保证不漂移）"""
    title: str
    preconditions: list[str]
    steps: list[dict]       # [{"action": "...", "input": "...", "expected": "..."}]
    assertions: list[str]
    priority: str           # P0/P1/P2
    tags: list[str]


class AgentState(TypedDict, total=False):
    """LangGraph 工作流全局状态"""

    # 输入
    requirement: str                    # 原始需求文本
    project_id: str
    knowledge_ids: list[str]            # RAG 检索到的知识片段

    # RAG
    retrieved_context: list[dict]       # [{"content": ..., "score": ..., "source": ...}]

    # 生成
    test_cases: list[TestCase]
    api_test_code: str                  # 生成的 pytest 代码
    ui_test_code: str                   # 生成的 Playwright 代码

    # 执行
    execution_results: list[dict]      # [{"case_id": ..., "passed": ..., "error": ...}]

    # 自愈
    heal_attempts: int
    healed_locators: list[dict]         # [{"old": ..., "new": ..., "confidence": ...}]
    final_status: str                   # "passed" / "failed" / "healed"

    # 元信息
    retry_budget: int                   # 自愈重试预算（防成本失控）
    error: Optional[str]
