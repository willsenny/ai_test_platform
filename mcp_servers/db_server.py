"""
数据库断言 MCP Server (stdio)

提供工具：
- query:        执行 SQL 查询
- assert_count: 行数断言
- assert_exists: 记录存在性断言

用于数据一致性校验：API 操作后验证数据库状态。
"""
import json as _json
import os

from mcp.server import MCPServer

mcp = MCPServer("db-assert")


# 连接池管理（简化版，生产用 asyncpg/aiomysql）
_CONNECTIONS: dict[str, "asyncpg.Connection"] = {}


# ============================================================
# 工具定义
# ============================================================
@mcp.tool(name="query", description="执行 SELECT 查询，返回 JSON 行数组")
async def query(sql: str, connection: str = "default") -> str:
    conn = await _get_connection(connection)
    rows = await conn.fetch(sql)
    return _json.dumps([dict(row) for row in rows], ensure_ascii=False, default=str)


@mcp.tool(name="assert_count", description="断言查询结果行数")
async def assert_count(sql: str, expected: int) -> str:
    conn = await _get_connection()
    count = await conn.fetchval(f"SELECT COUNT(*) FROM ({sql}) AS sub")
    passed = count == expected
    return _json.dumps({
        "passed": passed,
        "expected": expected,
        "actual": count,
    }, ensure_ascii=False)


@mcp.tool(name="assert_exists", description="断言某条记录存在")
async def assert_exists(table: str, where: str) -> str:
    conn = await _get_connection()
    sql = f"SELECT EXISTS(SELECT 1 FROM {table} WHERE {where})"
    exists = await conn.fetchval(sql)
    return _json.dumps({
        "passed": bool(exists),
        "table": table,
        "where": where,
    }, ensure_ascii=False)


async def _get_connection(name: str = "default"):
    if name not in _CONNECTIONS:
        import asyncpg

        dsn = os.getenv(f"DATABASE_URL_{name.upper()}", os.getenv("DATABASE_URL"))
        _CONNECTIONS[name] = await asyncpg.connect(dsn)
    return _CONNECTIONS[name]


if __name__ == "__main__":
    mcp.run("stdio")
