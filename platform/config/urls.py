"""
URL 配置（沿用 WHartTest DRF 结构）
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Django Admin
    path("admin/", admin.site.urls),

    # API 文档
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    # API v1 (沿用 WHartTest RESTful 风格)
    path("api/v1/", include([
        # 项目管理 (复用 WHartTest)
        path("projects/", include("apps.core.urls")),
        # 用例库 (复用 + 扩充)
        path("testcases/", include("apps.testcases.urls")),
        # RAG 知识库
        path("rag/", include("apps.rag.urls")),
        # Agent 编排
        path("agent/", include("apps.agent.urls")),
        # MCP 管理
        path("mcp/", include("apps.mcp.urls")),
        # 执行器
        path("executor/", include("apps.executor.urls")),
        # 自愈
        path("selfheal/", include("apps.selfheal.urls")),
    ])),
]
