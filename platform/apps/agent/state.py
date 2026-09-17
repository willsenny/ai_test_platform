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

    # Phase I 需求文档驱动
    scenario: dict                      # 单个解析场景（title/type/spec/...）
    case_type: str                      # "ui" | "api"
    project_ref_pk: int                 # core.Project 主键
    api_base_url: str                   # API 根地址覆盖（可空）
    source: str                         # 用例来源标记

    # RAG
    retrieved_context: list[dict]       # [{"content": ..., "score": ..., "source": ...}]

    # Phase G RAG
    retrieved_cases: list[dict]         # [{"id", "payload", "score"}] 历史相似用例
    few_shot_used: int                  # 注入生成器的历史用例数

    # 生成
    test_cases: list[TestCase]
    api_test_code: str                  # 生成的 pytest 代码
    ui_test_code: str                   # 生成的 Playwright 代码

    # Phase C 最小闭环
    plan: list[str]                     # planner 节点的执行计划
    case_count: int                     # 期望生成的用例数
    saved_ids: list[int]                # reporter 写入 DB 后的主键

    # Phase D 执行
    execute: bool                       # 是否在生成后自动执行
    execution_run_id: int               # Phase E: TestRun 批次主键
    execution_report: dict              # Phase E: 报告路径 {"json","html"}

    # Phase F 自愈
    self_heal: bool                     # 执行失败后是否自动自愈
    inject_failure: str                 # 演示用：selector/assertion/timing/none
    heal_results: list[dict]            # 自愈结果

    # 执行
    execution_results: list[dict]      # [{"case_id": ..., "passed": ..., "error": ...}]

    # 自愈
    heal_attempts: int
    healed_locators: list[dict]         # [{"old": ..., "new": ..., "confidence": ...}]
    final_status: str                   # "passed" / "failed" / "healed"

    # 元信息
    retry_budget: int                   # 自愈重试预算（防成本失控）
    error: Optional[str]
