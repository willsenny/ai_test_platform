"""
自愈 API

POST /api/v1/selfheal/heal - 触发五段闭环自愈
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .engine import FailureContext, heal_failure


class SelfHealView(APIView):
    """POST /api/v1/selfheal/heal"""

    async def post(self, request):
        data = request.data
        if not data.get("test_id"):
            return Response(
                {"error": "test_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        failure = FailureContext(
            test_id=data["test_id"],
            error_message=data.get("error_message", ""),
            stack_trace=data.get("stack_trace", ""),
            screenshot_path=data.get("screenshot_path"),
            page_url=data.get("page_url"),
            html_snippet=data.get("html_snippet"),
            locator=data.get("locator"),
        )
        retry_budget = int(data.get("retry_budget", 3))
        result, pr_result = await heal_failure(failure, retry_budget=retry_budget)

        return Response({
            "heal_result": {
                "success": result.success,
                "strategy": result.strategy,
                "old_locator": result.old_locator,
                "new_locator": result.new_locator,
                "confidence": result.confidence,
                "retries": result.retries,
            },
            "pr": pr_result,
        })
