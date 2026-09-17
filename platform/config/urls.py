"""
URL 配置（沿用 WHartTest DRF 结构）
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.urls import web_urlpatterns as core_web_urlpatterns

urlpatterns = [
    # Django Admin
    path("admin/", admin.site.urls),

    # Phase I Web 入口（项目 / 上传 / 批次 / 报告）
    path("", include(core_web_urlpatterns)),

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

# 开发期：提供执行报告 media 静态访问
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
