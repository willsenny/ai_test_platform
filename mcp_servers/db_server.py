"""
数据库断言 MCP Server (stdio)

提供工具：
- query:        执行 SQL 查询
- assert_count: 行数断言
- assert_exists: 记录存在性断言
- assert_equal: 字段值断言

用于数据一致性校验：API 操作后验证数据库状态。
"""
import asyncio
import json
from contextlib import contextmanager
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


server = Server("db-assert")


# 连接池管理（简化版，生产用 asyncpg/aiomysql）
_CONNECTIONS: dict[str, "asyncpg.Connection"] = {}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query",
            description="执行 SELECT 查询",
            input_schema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "connection": {"type": "string", "default": "default"},
                },
                "required": ["sql"],
            },
        ),
        Tool(
            name="assert_count",
            description="断言查询结果行数",
            input_schema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "expected": {"type": "integer"},
                },
                "required": ["sql", "expected"],
            },
        ),
        Tool(
            name="assert_exists",
            description="断言某条记录存在",
            input_schema={
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "where": {"type": "string"},
                },
                "required": ["table", "where"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "query":
        return await _query(arguments)
    elif name == "assert_count":
        return await _assert_count(arguments)
    elif name == "assert_exists":
        return await _assert_exists(arguments)
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _get_connection(name: str = "default"):
    """获取/创建数据库连接"""
    if name not in _CONNECTIONS:
        import asyncpg
        import os
        dsn = os.getenv(f"DATABASE_URL_{name.upper()}", os.getenv("DATABASE_URL"))
        _CONNECTIONS[name] = await asyncpg.connect(dsn)
    return _CONNECTIONS[name]


async def _query(args: dict) -> list[TextContent]:
    conn = await _get_connection(args.get("connection", "default"))
    rows = await conn.fetch(args["sql"])
    result = [dict(row) for row in rows]
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]


async def _assert_count(args: dict) -> list[TextContent]:
    conn = await _get_connection()
    count = await conn.fetchval(f"SELECT COUNT(*) FROM ({args['sql']}) AS sub")
    passed = count == args["expected"]
    return [TextContent(type="text", text=json.dumps({
        "passed": passed,
        "expected": args["expected"],
        "actual": count,
    }, ensure_ascii=False))]


async def _assert_exists(args: dict) -> list[TextContent]:
    conn = await _get_connection()
    sql = f"SELECT EXISTS(SELECT 1 FROM {args['table']} WHERE {args['where']})"
    exists = await conn.fetchval(sql)
    return [TextContent(type="text", text=json.dumps({
        "passed": bool(exists),
        "table": args["table"],
        "where": args["where"],
    }, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
