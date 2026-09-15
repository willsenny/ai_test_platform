"""
模型路由：Flash-Only Mode (DeepSeek V4.1 Flash)

核心原则：
- 唯一模型：DeepSeek V4.1 Flash (552B MoE, 原生多模态)
- 通过 reasoning_effort 参数区分思考深度（low/high）
- 本地 Ollama 作为离线兜底（可选）
- 成本极低：~$0.14/M input, ~$0.28/M output

2026-09 更新：
- Sonnet 弃用（翻墙+合规风险）
- V4 Pro 已路由到 V4.1 Flash（按 Flash 计费）
- 不再需要多模型路由，统一 Flash 一把梭
"""
from enum import Enum
from functools import lru_cache
from typing import Literal, Optional
from pydantic import BaseModel, Field
import os


# ─── 模式 ────────────────────────────────────────────────

class ReasoningLevel(str, Enum):
    LOW = "low"      # 快速生成（用例/代码/步骤）
    HIGH = "high"    # 深度思考（重构/根因/自愈）


# ─── 配置 ─────────────────────────────────────────────────

class ModelConfig(BaseModel):
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str
    reasoning_effort: Optional[str] = None  # None=off, "low"/"high"
    max_retries: int = 2
    timeout: int = 120
    source: str = "deepseek-v4.1-flash"


# ─── 定价（2026-09 DeepSeek 官方） ──────────────────────

PRICING = {
    "flash": {"input": 0.14, "output": 0.28, "cached": 0.0028},
}


# ─── 任务类型 → reasoning 档位映射 ───────────────────────

TASK_ROUTING: dict[str, ReasoningLevel] = {
    # LOW: 快速生成类（默认，占 ~90%）
    "generate_testcase": ReasoningLevel.LOW,
    "generate_steps": ReasoningLevel.LOW,
    "generate_assertion": ReasoningLevel.LOW,
    "refine_locator": ReasoningLevel.LOW,
    "summarize_log": ReasoningLevel.LOW,
    "classify_failure": ReasoningLevel.LOW,
    "draft_pr_description": ReasoningLevel.LOW,
    "generate_api_tests": ReasoningLevel.LOW,
    "generate_ui_tests": ReasoningLevel.LOW,
    "rag_ingest": ReasoningLevel.LOW,

    # HIGH: 深度思考类（~10%）
    "refactor_code": ReasoningLevel.HIGH,
    "design_workflow": ReasoningLevel.HIGH,
    "review_code": ReasoningLevel.HIGH,
    "analyze_dependencies": ReasoningLevel.HIGH,
    "root_cause_analysis": ReasoningLevel.HIGH,
    "self_heal_repair": ReasoningLevel.HIGH,
    "complex_debugging": ReasoningLevel.HIGH,
}


# ─── 核心函数 ─────────────────────────────────────────────

def get_config(
    reasoning: ReasoningLevel = ReasoningLevel.LOW,
    use_local: bool = False,
) -> ModelConfig:
    """
    获取模型配置
    
    Args:
        reasoning: 思考深度（low=快速, high=深度）
        use_local: True=走 Ollama 本地兜底
    """
    if use_local:
        return ModelConfig(
            model="qwen2.5-coder:14b",
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama",
            source="local-ollama",
        )
    
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not set. "
            "Add to ~/.zshrc: export DEEPSEEK_API_KEY='sk-...'"
        )
    
    return ModelConfig(
        model="deepseek-flash",
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
        reasoning_effort=reasoning.value if reasoning != ReasoningLevel.LOW else None,
    )


def route(task_type: str, *, force_reasoning: Optional[ReasoningLevel] = None, use_local: bool = False) -> ModelConfig:
    """
    根据任务类型返回模型配置（对外接口，兼容旧调用方式）
    
    Args:
        task_type: 任务类型 key（见 TASK_ROUTING）
        force_reasoning: 强制指定 reasoning 档位
        use_local: 走本地 Ollama 兜底
    """
    if use_local:
        return get_config(use_local=True)
    
    if force_reasoning:
        level = force_reasoning
    else:
        level = TASK_ROUTING.get(task_type, ReasoningLevel.LOW)
    
    return get_config(reasoning=level)


# ─── 便捷函数（兼容旧代码） ──────────────────────────────

def route_l1(task_type: str = "") -> ModelConfig:
    """兼容旧代码：L1 = Flash low"""
    return route(task_type or "generate_testcase")


def route_l2(task_type: str = "") -> ModelConfig:
    """兼容旧代码：L2 = Flash high"""
    return route(task_type or "refactor_code", force_reasoning=ReasoningLevel.HIGH)


def route_l3(task_type: str = "") -> ModelConfig:
    """兼容旧代码：L3 = 本地兜底（Sonnet 已弃用）"""
    return route(task_type or "self_heal_repair", use_local=True)


# ─── 成本追踪（简化版） ──────────────────────────────────

class CostTracker:
    """Flash-only 成本追踪"""

    def __init__(self):
        self.calls: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    def record(self, input_tokens: int, output_tokens: int):
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def total_usd(self) -> float:
        p = PRICING["flash"]
        return round(
            self.input_tokens / 1_000_000 * p["input"]
            + self.output_tokens / 1_000_000 * p["output"],
            4,
        )

    def report(self) -> str:
        return "\n".join([
            "=== Model Cost Report (Flash-Only) ===",
            f"  Calls:        {self.calls}",
            f"  Input tokens:  {self.input_tokens:,}",
            f"  Output tokens: {self.output_tokens:,}",
            f"  Total USD:    ${self.total_usd():.4f}",
            f"  Avg per call: ${self.total_usd() / max(self.calls, 1):.4f}",
        ])


@lru_cache(maxsize=1)
def get_cost_tracker() -> CostTracker:
    return CostTracker()