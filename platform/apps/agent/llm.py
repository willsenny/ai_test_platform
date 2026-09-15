"""
LLM 调用适配层

统一使用 litellm 调用，自动适配 DeepSeek / Claude / 本地模型。
配合 router.py 的分层路由，实现成本最优。
"""
import os
import json
from typing import Optional, Type, Any
from .router import ModelConfig, get_cost_tracker


async def call_llm(
    config: ModelConfig,
    prompt: str,
    *,
    system: str = "",
    temperature: float = 0.3,
    max_tokens: int = 4096,
    response_schema: Optional[Type] = None,
) -> dict:
    """
    统一 LLM 调用入口

    Args:
        config: 模型配置 (来自 router.route())
        prompt: 用户提示词
        system: 系统提示词
        temperature: 温度
        max_tokens: 最大输出
        response_schema: Pydantic schema (结构化输出)

    Returns:
        dict: {"content": str, "usage": {...}}

    Usage:
        cfg = route("generate_testcase")  # → L1 Flash
        result = await call_llm(cfg, prompt)
        # or with structured output:
        result = await call_llm(cfg, prompt, response_schema=TestCase)
    """
    try:
        from litellm import acompletion
    except ImportError:
        # Fallback: 直接调用 DeepSeek OpenAI 兼容接口
        return await _fallback_call(config, prompt, system)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": _to_litellm_model(config),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # 结构化输出 (DeepSeek 支持 response_format)
    if response_schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": _schema_to_json(response_schema),
        }

    response = await acompletion(**kwargs)

    content = response.choices[0].message.content
    usage = {
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
    }

    # 记录成本
    tracker = get_cost_tracker()
    tracker.record(config.tier, usage["input_tokens"], usage["output_tokens"])

    return {"content": content, "usage": usage}


def _to_litellm_model(config: ModelConfig) -> str:
    """转换为 litellm 模型标识符"""
    if "anthropic" in config.base_url:
        return f"anthropic/{config.model}"
    elif "deepseek" in config.base_url:
        return f"deepseek/{config.model}"
    else:
        # 自定义 OpenAI 兼容端点
        os.environ["OPENAI_API_BASE"] = config.base_url
        return f"openai/{config.model}"


def _schema_to_json(schema: Type) -> dict:
    """Pydantic schema → JSON Schema"""
    if hasattr(schema, "model_json_schema"):
        return schema.model_json_schema()
    return {}


async def _fallback_call(config: ModelConfig, prompt: str, system: str = "") -> dict:
    """无 litellm 时的降级实现 (直接 httpx 调用)"""
    import httpx

    headers = {
        "Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.timeout,
        )
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    tracker = get_cost_tracker()
    tracker.record(config.tier, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

    return {"content": content, "usage": usage}


# ============================================================
# 便捷函数：带重试的调用
# ============================================================
async def call_with_retry(
    config: ModelConfig,
    prompt: str,
    *,
    max_retries: int = 3,
    **kwargs,
) -> dict:
    """带指数退避的重试调用"""
    import asyncio

    last_error = None
    for attempt in range(max_retries):
        try:
            return await call_llm(config, prompt, **kwargs)
        except Exception as e:
            last_error = e
            wait = 2 ** attempt
            await asyncio.sleep(wait)

    raise RuntimeError(f"LLM call failed after {max_retries} retries: {last_error}")
