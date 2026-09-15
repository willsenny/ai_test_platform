"""
执行器 API

POST /api/v1/executor/ui/run   - 执行 UI 测试代码
POST /api/v1/executor/api/run  - 执行接口请求
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .executor import execute_ui_test, execute_api_test


class RunUITestView(APIView):
    """POST /api/v1/executor/ui/run"""

    async def post(self, request):
        test_code = request.data.get("test_code", "")
        if not test_code:
            return Response(
                {"error": "test_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = await execute_ui_test(
            test_code=test_code,
            test_file=request.data.get("test_file", "/tmp/exec_test.py"),
        )
        return Response({"result": result})


class RunAPITestView(APIView):
    """POST /api/v1/executor/api/run"""

    async def post(self, request):
        url = request.data.get("url")
        if not url:
            return Response(
                {"error": "url is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = await execute_api_test(
            method=request.data.get("method", "GET"),
            url=url,
            **request.data.get("kwargs", {}),
        )
        return Response({"result": result})
