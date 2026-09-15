"""
执行器：封装通过 MCP 执行测试的能力

- UI 测试: 走 Playwright MCP (stdio)
- API 测试: 走 API MCP (httpx + pytest)
- 数据断言: 走 DB MCP
"""
from typing import Any


async def execute_ui_test(test_code: str, test_file: str) -> Any:
    """通过 Playwright MCP 执行 UI 测试代码"""
    from apps.mcp.client import run_playwright_test

    return await run_playwright_test(test_code=test_code, test_file=test_file)


async def execute_api_test(method: str, url: str, **kwargs) -> Any:
    """通过 API MCP 执行接口请求"""
    from apps.mcp.client import run_api_test

    return await run_api_test(method, url, **kwargs)


async def query_database(sql: str, connection: str = "default") -> Any:
    """数据一致性断言：通过 DB MCP 查询"""
    from apps.mcp.client import query_database as _query

    return await _query(sql, connection)
