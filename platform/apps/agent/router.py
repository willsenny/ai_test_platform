"""
模型路由：L1 Flash (70%) / L2 Pro (25%) / L3 Sonnet (5%)

核心原则：
- 代码生成/批量任务 → Flash (便宜 21-53 倍，质量几乎无损)
- 多文件重构/复杂编排 → Pro
- 自愈/疑难根因 → Sonnet (兜底，极少调用)
"""
from enum import Enum
from functools import lru_cache
from pydantic import BaseModel
import os


class ModelTier(str, Enum):
    L1_FLASH = "l1_flash"   # DeepSeek V4 Flash - 批量主力
    L2_PRO = "l2_pro"       # DeepSeek V4 Pro - 复杂任务
    L3_SONNET = "l3_sonnet" # Claude Sonnet - 兜底


class ModelConfig(BaseModel):
    tier: ModelTier
    model: str
    base_url: str
    max_retries: int = 2
    timeout: int = 120


# 各层定价（每百万 token，2026 参考）
PRICING = {
    ModelTier.L1_FLASH:   {"input": 0.14, "output": 0.28, "cached": 0.0028},
    ModelTier.L2_PRO:     {"input": 0.435, "output": 2.5, "cached": 0.014},
    ModelTier.L3_SONNET:  {"input": 3.0, "output": 15.0, "cached": 0.30},
}


def get_config(tier: ModelTier) -> ModelConfig:
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    if tier == ModelTier.L3_SONNET:
        return ModelConfig(
            tier=tier,
            model=os.getenv("MODEL_L3", "claude-sonnet-4-6"),
            base_url="https://api.anthropic.com/v1",
            max_retries=3,
        )
    elif tier == ModelTier.L2_PRO:
        return ModelConfig(
            tier=tier,
            model=os.getenv("MODEL_L2", "deepseek-reasoner"),
            base_url=base,
        )
    else:
        return ModelConfig(
            tier=tier,
            model=os.getenv("MODEL_L1", "deepseek-chat"),
            base_url=base,
        )


# 任务类型 → 模型层级映射
TASK_ROUTING = {
    # L1: 批量、确定性任务 (70%)
    "generate_testcase": ModelTier.L1_FLASH,
    "generate_steps": ModelTier.L1_FLASH,
    "generate_assertion": ModelTier.L1_FLASH,
    "refine_locator": ModelTier.L1_FLASH,
    "summarize_log": ModelTier.L1_FLASH,
    "classify_failure": ModelTier.L1_FLASH,
    "draft_pr_description": ModelTier.L1_FLASH,

    # L2: 多文件/复杂编排 (25%)
    "refactor_code": ModelTier.L2_PRO,
    "design_workflow": ModelTier.L2_PRO,
    "review_code": ModelTier.L2_PRO,
    "generate_api_tests": ModelTier.L2_PRO,
    "analyze_dependencies": ModelTier.L2_PRO,

    # L3: 疑难根因/自愈 (5%)
    "root_cause_analysis": ModelTier.L3_SONNET,
    "self_heal_repair": ModelTier.L3_SONNET,
    "complex_debugging": ModelTier.L3_SONNET,
}


def route(task_type: str, *, force_tier: ModelTier | None = None) -> ModelConfig:
    """根据任务类型自动选择模型层级。"""
    if force_tier:
        return get_config(force_tier)
    tier = TASK_ROUTING.get(task_type, ModelTier.L1_FLASH)
    return get_config(tier)


class CostTracker:
    """追踪各层级 token 消耗，用于成本监控。"""

    def __init__(self):
        self.usage: dict[ModelTier, dict[str, int]] = {
            t: {"calls": 0, "input_tokens": 0, "output_tokens": 0}
            for t in ModelTier
        }

    def record(self, tier: ModelTier, input_tokens: int, output_tokens: int):
        u = self.usage[tier]
        u["calls"] += 1
        u["input_tokens"] += input_tokens
        u["output_tokens"] += output_tokens

    def total_usd(self) -> float:
        total = 0.0
        for tier, u in self.usage.items():
            p = PRICING[tier]
            total += u["input_tokens"] / 1_000_000 * p["input"]
            total += u["output_tokens"] / 1_000_000 * p["output"]
        return round(total, 4)

    def report(self) -> str:
        lines = ["=== Model Cost Report ===", f"{'Tier':<12}{'Calls':<8}{'USD':<10}"]
        for tier, u in self.usage.items():
            p = PRICING[tier]
            cost = (u["input_tokens"] / 1e6 * p["input"]
                    + u["output_tokens"] / 1e6 * p["output"])
            lines.append(f"{tier.value:<12}{u['calls']:<8}{cost:<10.4f}")
        lines.append(f"{'TOTAL':<12}{'':<8}{self.total_usd():<10.4f}")
        return "\n".join(lines)


# 全局单例（简单场景）
@lru_cache(maxsize=1)
def get_cost_tracker() -> CostTracker:
    return CostTracker()
