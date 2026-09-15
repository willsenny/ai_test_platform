"""
API 测试 MCP Server (stdio)

提供工具：
- request:         发起 HTTP 请求 (GET/POST/PUT/DELETE)
- assert_status:   状态码断言
- assert_json:     JSON 字段断言
- assert_schema:   JSON Schema 校验
- load_openapi:    从 OpenAPI 规范自动生成测试用例

配合 httpx + pytest 实现接口自动化。
"""
import asyncio
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


server = Server("api-test")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="request",
            description="发起 HTTP 请求",
            input_schema={
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                    "url": {"type": "string"},
                    "headers": {"type": "object"},
                    "json": {"type": "object"},
                    "params": {"type": "object"},
                },
                "required": ["method", "url"],
            },
        ),
        Tool(
            name="assert_status",
            description="断言响应状态码",
            input_schema={
                "type": "object",
                "properties": {
                    "expected": {"type": "integer"},
                    "actual": {"type": "integer"},
                },
                "required": ["expected", "actual"],
            },
        ),
        Tool(
            name="assert_json",
            description="断言 JSON 响应中的字段值",
            input_schema={
                "type": "object",
                "properties": {
                    "response": {"type": "object"},
                    "path": {"type": "string", "description": "JSONPath 表达式"},
                    "expected": {"type": "string"},
                },
                "required": ["response", "path", "expected"],
            },
        ),
        Tool(
            name="load_openapi",
            description="加载 OpenAPI 规范，自动生成接口测试用例",
            input_schema={
                "type": "object",
                "properties": {
                    "spec_url": {"type": "string", "description": "OpenAPI JSON URL"},
                },
                "required": ["spec_url"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "request":
        return await _request(arguments)
    elif name == "assert_status":
        return await _assert_status(arguments)
    elif name == "assert_json":
        return await _assert_json(arguments)
    elif name == "load_openapi":
        return await _load_openapi(arguments)
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _request(args: dict) -> list[TextContent]:
    """使用 httpx 发起异步 HTTP 请求"""
    import httpx

    method = args["method"]
    url = args["url"]
    headers = args.get("headers", {})
    json_body = args.get("json")
    params = args.get("params")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            params=params,
        )

    result = {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "body": _safe_json(resp),
        "elapsed_ms": resp.elapsed.total_seconds() * 1000,
    }
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def _assert_status(args: dict) -> list[TextContent]:
    expected = args["expected"]
    actual = args["actual"]
    passed = expected == actual
    return [TextContent(type="text", text=json.dumps({
        "passed": passed,
        "expected": expected,
        "actual": actual,
        "message": "" if passed else f"Expected {expected}, got {actual}",
    }, ensure_ascii=False))]


async def _assert_json(args: dict) -> list[TextContent]:
    """使用 JSONPath 提取字段并断言"""
    import jsonpath_ng
    response = args["response"]
    path_expr = args["path"]
    expected = args["expected"]

    jsonpath_expr = jsonpath_ng.parse(path_expr)
    matches = [match.value for match in jsonpath_expr.find(response)]
    passed = expected in [str(m) for m in matches]

    return [TextContent(type="text", text=json.dumps({
        "passed": passed,
        "matches": matches,
        "expected": expected,
    }, ensure_ascii=False))]


async def _load_openapi(args: dict) -> list[TextContent]:
    """
    从 OpenAPI 规范自动生成接口测试用例。
    遍历所有 path + method，生成正向/异常用例。
    """
    import httpx

    spec_url = args["spec_url"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(spec_url)
        spec = resp.json()

    test_cases = []
    for path, operations in spec.get("paths", {}).items():
        for method, operation in operations.items():
            # 正向用例
            test_cases.append({
                "name": f"test_{operation.get('operationId', method + path)}",
                "method": method.upper(),
                "path": path,
                "type": "positive",
            })
            # 参数缺失异常
            if operation.get("parameters"):
                test_cases.append({
                    "name": f"test_{operation.get('operationId', method + path)}_missing_param",
                    "method": method.upper(),
                    "path": path,
                    "type": "negative",
                })

    return [TextContent(type="text", text=json.dumps({
        "total": len(test_cases),
        "test_cases": test_cases,
    }, ensure_ascii=False, indent=2))]


def _safe_json(resp: "httpx.Response") -> dict:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
