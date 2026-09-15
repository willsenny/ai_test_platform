"""
Echo MCP Server (stdio, JSON-RPC)

Phase C 最小闭环用的确定性 MCP Server，供 LangGraph generator 节点通过 stdio 调用，
证明 Django → LangGraph → MCP(stdio) 链路可用。

工具：
- echo:                原样回显文本（连通性验证）
- fake_generate_test:  根据 goal 生成确定性 TestCase 列表（不调用 LLM）

输出结构对齐 apps.agent.state.TestCase。
"""
import json
import sys
from pathlib import Path

from mcp.server import MCPServer

mcp = MCPServer("echo")

# 本地登录示例页，供 Playwright executor 真执行（file:// 无需外部服务）
_FIXTURE = (Path(__file__).resolve().parents[1] / "mcp_servers" / "fixtures" / "login.html")
_TARGET_URL = _FIXTURE.as_uri()


@mcp.tool(
    name="echo",
    description="原样回显输入文本，用于验证 stdio MCP 连通性。",
)
async def echo(text: str) -> str:
    return f"echo: {text}"


def _extract_selectors(few_shot: str) -> dict:
    """从 few-shot（历史用例 JSON）里提取 selector 模式，按角色归类。

    Phase G：让生成结果复用历史 selector（演示 RAG 对生成的影响）。
    """
    role_markers = {
        "phone": ("phone", "tel", "mobile", "手机"),
        "code": ("code", "captcha", "verify", "验证码", "短信"),
        "submit": ("submit", "login", "signin", "登录", "提交"),
        "result": ("result", "message", "msg", "结果", "提示"),
    }
    found: dict[str, str] = {}
    try:
        cases = json.loads(few_shot) if few_shot else []
    except (ValueError, TypeError):
        cases = []

    for case in cases if isinstance(cases, list) else []:
        for step in case.get("steps", []) if isinstance(case, dict) else []:
            selector = str(step.get("selector", "") or "")
            if not selector:
                continue
            haystack = f"{selector} {step.get('description', '')}".lower()
            for role, markers in role_markers.items():
                if role not in found and any(m in haystack for m in markers):
                    found[role] = selector
    return found


@mcp.tool(
    name="fake_generate_test",
    description=(
        "根据测试目标生成结构化的可执行测试用例（确定性、不调用 LLM）。"
        "steps 含 action(selector/value)，assertions 含断言类型；返回 JSON 字符串。"
        "few_shot 可传入历史用例 JSON，生成时复用其中的 selector 模式。"
    ),
)
async def fake_generate_test(goal: str, count: int = 3, few_shot: str = "") -> str:
    count = max(1, min(int(count), 20))

    # Phase G：优先复用历史 selector；无历史时用默认 selector
    hist = _extract_selectors(few_shot)
    sel_phone = hist.get("phone", "#phone")
    sel_code = hist.get("code", "#code")
    sel_submit = hist.get("submit", "#submit")
    sel_result = hist.get("result", "#result")

    # (场景, 优先级, 验证码, 期望结果)
    scenarios = [
        ("正常流程", "P0", "123456", "登录成功"),
        ("边界条件", "P1", "000000", "登录成功"),
        ("异常输入", "P2", "", "登录失败"),
    ]

    test_cases = []
    for i in range(count):
        label, priority, code, expected_text = scenarios[i % len(scenarios)]
        test_cases.append(
            {
                "title": f"{goal} - {label} #{i + 1}",
                "preconditions": ["本地登录页可访问 (file:// fixtures/login.html)"],
                "target_url": _TARGET_URL,
                "steps": [
                    {
                        "action": "goto",
                        "selector": "",
                        "value": _TARGET_URL,
                        "description": "打开登录页",
                    },
                    {
                        "action": "fill",
                        "selector": sel_phone,
                        "value": "13800138000",
                        "description": "输入手机号",
                    },
                    {
                        "action": "fill",
                        "selector": sel_code,
                        "value": code,
                        "description": f"输入验证码 ({label})",
                    },
                    {
                        "action": "click",
                        "selector": sel_submit,
                        "value": "",
                        "description": "点击登录",
                    },
                ],
                "assertions": [
                    {
                        "type": "text_contains",
                        "selector": sel_result,
                        "expected": expected_text,
                    }
                ],
                "priority": priority,
                "tags": ["phase-d", "login", label],
            }
        )

    return json.dumps(test_cases, ensure_ascii=False)



def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
