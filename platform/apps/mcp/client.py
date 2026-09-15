"""
MCP 客户端：统一管理 stdio (本地) + SSE (远程) MCP Server

注册的 MCP Server:
- playwright: 官方 Playwright MCP (stdio) - 真浏览器操作
- api:       API 测试 (httpx) - 接口调用 + 断言
- db:        数据库断言 - 数据一致性校验
- git:       Git 操作 - 自愈后自动开 PR

注意：WHartTest 仅支持 HTTP/SSE MCP，本项目额外支持 stdio，
     以兼容 OpenCode / Claude Code 生态。
"""
import os
import json
import asyncio
from typing import Any, Optional
from contextlib import AsyncExitStack


class MCPClient:
    """
    MCP 客户端管理器

    Usage:
        async with MCPClient() as client:
            result = await client.call_tool("playwright", "run_tests", {...})
    """

    def __init__(self):
        self._stack = AsyncExitStack()
        self._sessions: dict[str, Any] = {}
        self._config: dict[str, dict] = {}

    async def __aenter__(self):
        await self._load_config()
        await self._connect_all()
        return self

    async def __aexit__(self, *args):
        await self._stack.aclose()

    async def _load_config(self):
        """从配置文件加载 MCP Server 定义"""
        config_path = os.getenv(
            "MCP_CONFIG",
            os.path.join(os.path.dirname(__file__), "config.json"),
        )
        if os.path.exists(config_path):
            with open(config_path) as f:
                self._config = json.load(f)

    async def _connect_all(self):
        """连接所有配置的 MCP Server"""
        for name, cfg in self._config.items():
            transport = cfg.get("transport", "stdio")
            if transport == "stdio":
                await self._connect_stdio(name, cfg)
            elif transport in ("sse", "http"):
                await self._connect_sse(name, cfg)

    async def _connect_stdio(self, name: str, cfg: dict):
        """连接 stdio MCP Server (如官方 Playwright MCP)"""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args", []),
            env=cfg.get("env"),
        )
        # 使用 exit stack 管理生命周期
        read, write = await self._stack.enter_async_context(
            stdio_client(params)
        )
        session = await self._stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        self._sessions[name] = session

    async def _connect_sse(self, name: str, cfg: dict):
        """连接 SSE/HTTP MCP Server (兼容 WHartTest 的 HTTP MCP)"""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        url = cfg["url"]
        read, write = await self._stack.enter_async_context(
            sse_client(url)
        )
        session = await self._stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        self._sessions[name] = session

    async def call_tool(
        self,
        server: str,
        tool: str,
        arguments: dict,
    ) -> Any:
        """调用指定 MCP Server 的工具"""
        session = self._sessions.get(server)
        if not session:
            raise RuntimeError(f"MCP server '{server}' not connected")
        result = await session.call_tool(tool, arguments)
        return _parse_tool_result(result)

    async def list_tools(self, server: str) -> list[dict]:
        """列出指定 Server 的所有工具"""
        session = self._sessions.get(server)
        if not session:
            return []
        resp = await session.list_tools()
        return [
            {"name": t.name, "description": t.description, "schema": t.input_schema}
            for t in resp.tools
        ]

    async def list_all_tools(self) -> dict[str, list[dict]]:
        """列出所有 Server 的工具（供 Agent 选择）"""
        result = {}
        for name in self._sessions:
            result[name] = await self.list_tools(name)
        return result


def _parse_tool_result(result: Any) -> Any:
    """解析 MCP 工具返回结果"""
    if hasattr(result, "content"):
        # 提取文本内容
        texts = []
        for item in result.content:
            if hasattr(item, "text"):
                texts.append(item.text)
        return "\n".join(texts) if texts else result
    return result


# ============================================================
# 便捷函数（无需上下文管理器时使用）
# ============================================================
_client: Optional[MCPClient] = None


async def get_client() -> MCPClient:
    """获取全局 MCP 客户端（懒加载单例）"""
    global _client
    if _client is None:
        _client = MCPClient()
        await _client.__aenter__()
    return _client


async def call_tool(server: str, tool: str, arguments: dict) -> Any:
    """便捷调用"""
    client = await get_client()
    return await client.call_tool(server, tool, arguments)


# ============================================================
# 常用工具封装
# ============================================================
async def run_playwright_test(test_code: str, test_file: str) -> dict:
    """通过 Playwright MCP 执行 UI 测试"""
    return await call_tool("playwright", "run_tests", {
        "test_code": test_code,
        "test_file": test_file,
    })


async def run_api_test(method: str, url: str, **kwargs) -> dict:
    """通过 API MCP 执行接口测试"""
    return await call_tool("api", "request", {
        "method": method,
        "url": url,
        **kwargs,
    })


async def query_database(sql: str, connection: str = "default") -> list[dict]:
    """通过 DB MCP 查询数据库（数据一致性断言）"""
    return await call_tool("db", "query", {
        "sql": sql,
        "connection": connection,
    })


async def create_pr(title: str, body: str, branch: str, files: dict) -> dict:
    """通过 Git MCP 自动开 PR（自愈修复后）"""
    return await call_tool("git", "create_pull_request", {
        "title": title,
        "body": body,
        "branch": branch,
        "files": files,
    })
