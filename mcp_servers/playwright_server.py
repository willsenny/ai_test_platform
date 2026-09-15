"""
Playwright MCP Server (stdio)

提供工具：
- run_tests:       执行 pytest + playwright 测试
- snapshot:        获取页面 accessibility tree
- click:           点击元素
- fill:            填写输入框
- navigate:        导航到 URL
- get_locator:     获取元素定位器（供自愈使用）

设计原则：基于 accessibility snapshot，无需视觉模型。
"""
import asyncio
import json
import tempfile
import os
from pathlib import Path


# ============================================================
# MCP Server 框架 (使用 mcp-python SDK)
# ============================================================
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


server = Server("playwright-test")


# ============================================================
# 工具定义
# ============================================================
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="run_tests",
            description="执行 Playwright 测试文件，返回结果",
            input_schema={
                "type": "object",
                "properties": {
                    "test_code": {"type": "string", "description": "测试代码内容"},
                    "test_file": {"type": "string", "description": "测试文件路径"},
                    "browser": {"type": "string", "default": "chromium"},
                },
                "required": ["test_code", "test_file"],
            },
        ),
        Tool(
            name="snapshot",
            description="获取当前页面的 accessibility tree snapshot",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "页面 URL"},
                },
            },
        ),
        Tool(
            name="click",
            description="点击指定定位器的元素",
            input_schema={
                "type": "object",
                "properties": {
                    "locator": {"type": "string"},
                    "selector": {"type": "string"},
                },
                "required": ["locator"],
            },
        ),
        Tool(
            name="fill",
            description="填写输入框",
            input_schema={
                "type": "object",
                "properties": {
                    "locator": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["locator", "value"],
            },
        ),
        Tool(
            name="get_locator",
            description="获取元素的推荐定位器 (供自愈定位器库使用)",
            input_schema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "元素描述"},
                },
                "required": ["description"],
            },
        ),
    ]


# ============================================================
# 工具实现
# ============================================================
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "run_tests":
        return await _run_tests(arguments)
    elif name == "snapshot":
        return await _snapshot(arguments)
    elif name == "click":
        return await _click(arguments)
    elif name == "fill":
        return await _fill(arguments)
    elif name == "get_locator":
        return await _get_locator(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _run_tests(args: dict) -> list[TextContent]:
    """写入测试文件并执行 pytest"""
    test_code = args["test_code"]
    test_file = args["test_file"]

    # 确保目录存在
    Path(test_file).parent.mkdir(parents=True, exist_ok=True)

    # 写入测试文件
    with open(test_file, "w") as f:
        f.write(test_code)

    # 执行 pytest (异步子进程)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent / "platform")

    proc = await asyncio.create_subprocess_exec(
        "pytest",
        test_file,
        "-v",
        "--tb=json",
        "--json-report",
        "--json-report-file=/tmp/pytest_report.json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()

    # 解析结果
    report = {}
    if Path("/tmp/pytest_report.json").exists():
        with open("/tmp/pytest_report.json") as f:
            report = json.load(f)

    result = {
        "exit_code": proc.returncode,
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "summary": report.get("summary", {}),
        "tests": [
            {
                "nodeid": t["nodeid"],
                "outcome": t["outcome"],
                "error": t.get("longrepr", ""),
            }
            for t in report.get("tests", [])
        ],
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def _snapshot(args: dict) -> list[TextContent]:
    """获取页面 accessibility snapshot (无需视觉模型)"""
    url = args.get("url", "")
    # 实际实现使用 playwright.async_api
    # 这里返回结构示意
    snapshot = {
        "url": url,
        "title": "",
        "elements": [
            # {"role": "button", "name": "登录", "selector": "button:has-text('登录')"}
        ],
    }
    return [TextContent(type="text", text=json.dumps(snapshot, ensure_ascii=False))]


async def _click(args: dict) -> list[TextContent]:
    """点击元素"""
    locator = args["locator"]
    # 实际: await page.click(locator)
    return [TextContent(type="text", text=json.dumps({"clicked": locator}))]


async def _fill(args: dict) -> list[TextContent]:
    """填写输入框"""
    locator = args["locator"]
    value = args["value"]
    # 实际: await page.fill(locator, value)
    return [TextContent(type="text", text=json.dumps({"filled": locator, "value": value}))]


async def _get_locator(args: dict) -> list[TextContent]:
    """
    基于 accessibility tree 推荐定位器。
    优先级：role+name > text > CSS > XPath
    """
    description = args["description"]
    # 实际: 从 snapshot 中匹配元素，生成推荐定位器
    candidates = [
        {"strategy": "role", "locator": f"role=button[name='{description}']", "score": 0.95},
        {"strategy": "text", "locator": f"text='{description}'", "score": 0.80},
        {"strategy": "css", "locator": f"[data-testid='{description}']", "score": 0.60},
    ]
    return [TextContent(type="text", text=json.dumps(candidates, ensure_ascii=False))]


# ============================================================
# 入口
# ============================================================
async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
