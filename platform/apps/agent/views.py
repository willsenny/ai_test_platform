"""
Agent API 端点

POST /api/v1/agent/generate   - 触发测试生成工作流
GET  /api/v1/agent/status/{id} - 查询执行状态
POST /api/v1/agent/heal        - 触发自愈
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .graph import run_test_workflow
from .router import get_cost_tracker


class GenerateTestView(APIView):
    """
    POST /api/v1/agent/generate

    Body:
        {
            "requirement": "用户登录功能，支持手机号+验证码",
            "project_id": "proj_123",
            "retry_budget": 3
        }

    Response:
        {
            "status": "completed",
            "test_cases": [...],
            "api_test_code": "...",
            "ui_test_code": "...",
            "execution_results": [...],
            "final_status": "passed",
            "cost_usd": 0.042
        }
    """

    async def post(self, request):
        requirement = request.data.get("requirement")
        if not requirement:
            return Response(
                {"error": "requirement is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project_id = request.data.get("project_id", "")
        retry_budget = int(request.data.get("retry_budget", 3))

        # 记录初始成本
        tracker = get_cost_tracker()
        cost_before = tracker.total_usd()

        try:
            result = await run_test_workflow(
                requirement=requirement,
                project_id=project_id,
                retry_budget=retry_budget,
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        cost_after = tracker.total_usd()
        result["cost_usd"] = round(cost_after - cost_before, 4)

        return Response(result)


class CostReportView(APIView):
    """
    GET /api/v1/agent/cost

    返回模型成本报告
    """

    def get(self, request):
        tracker = get_cost_tracker()
        return Response({
            "report": tracker.report(),
            "total_usd": tracker.total_usd(),
        })


class HealView(APIView):
    """
    POST /api/v1/agent/heal

    Body:
        {
            "test_id": "login_001",
            "error_message": "TimeoutError: waiting for selector",
            "locator": "#submit-btn",
            "page_url": "https://example.com/login"
        }
    """

    async def post(self, request):
        from apps.selfheal.engine import heal_failure, FailureContext

        data = request.data
        failure = FailureContext(
            test_id=data["test_id"],
            error_message=data.get("error_message", ""),
            stack_trace=data.get("stack_trace", ""),
            screenshot_path=data.get("screenshot_path"),
            page_url=data.get("page_url"),
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
