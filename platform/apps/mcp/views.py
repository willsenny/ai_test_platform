"""
MCP 管理 API

GET /api/v1/mcp/tools - 列出所有已连接 Server 的工具（供 Agent 选择）
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from .client import get_client


class ToolListView(APIView):
    """GET /api/v1/mcp/tools"""

    async def get(self, request):
        client = await get_client()
        return Response(await client.list_all_tools())
