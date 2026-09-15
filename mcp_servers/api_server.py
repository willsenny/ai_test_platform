"""
API 测试 MCP Server (stdio)

提供工具：
- request:         发起 HTTP 请求 (GET/POST/PUT/DELETE)
- assert_status:   状态码断言
- assert_json:     JSON 字段断言
- load_openapi:    从 OpenAPI 规范自动生成测试用例

配合 httpx + pytest 实现接口自动化。
"""
import json as _json

from mcp.server import MCPServer

mcp = MCPServer("api-test")


# ============================================================
# 工具定义
# ============================================================
@mcp.tool(name="request", description="发起 HTTP 请求（返回 JSON 字符串）")
async def request(
    method: str,
    url: str,
    headers: dict | None = None,
    json: dict | None = None,
    params: dict | None = None,
) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(
            method=method,
            url=url,
            headers=headers or {},
            json=json,
            params=params,
        )

    result = {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "body": _safe_json(resp),
        "elapsed_ms": resp.elapsed.total_seconds() * 1000,
    }
    return _json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool(name="assert_status", description="断言响应状态码")
async def assert_status(expected: int, actual: int) -> str:
    passed = expected == actual
    return _json.dumps({
        "passed": passed,
        "expected": expected,
        "actual": actual,
        "message": "" if passed else f"Expected {expected}, got {actual}",
    }, ensure_ascii=False)


@mcp.tool(name="assert_json", description="断言 JSON 响应中的字段值（JSONPath）")
async def assert_json(response: dict, path: str, expected: str) -> str:
    import jsonpath_ng

    jsonpath_expr = jsonpath_ng.parse(path)
    matches = [match.value for match in jsonpath_expr.find(response)]
    passed = expected in [str(m) for m in matches]

    return _json.dumps({
        "passed": passed,
        "matches": matches,
        "expected": expected,
    }, ensure_ascii=False)


@mcp.tool(
    name="load_openapi",
    description="加载 OpenAPI 规范，自动生成接口测试用例（正向/异常）",
)
async def load_openapi(spec_url: str) -> str:
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(spec_url)
        spec = resp.json()

    test_cases = []
    for path, operations in spec.get("paths", {}).items():
        for method, operation in operations.items():
            test_cases.append({
                "name": f"test_{operation.get('operationId', method + path)}",
                "method": method.upper(),
                "path": path,
                "type": "positive",
            })
            if operation.get("parameters"):
                test_cases.append({
                    "name": f"test_{operation.get('operationId', method + path)}_missing_param",
                    "method": method.upper(),
                    "path": path,
                    "type": "negative",
                })

    return _json.dumps({
        "total": len(test_cases),
        "test_cases": test_cases,
    }, ensure_ascii=False, indent=2)


def _safe_json(resp) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


if __name__ == "__main__":
    mcp.run("stdio")
