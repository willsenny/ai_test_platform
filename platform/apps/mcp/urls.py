"""
MCP URLs（挂载于 /api/v1/mcp/）
"""
from django.urls import path

from . import views

urlpatterns = [
    path("tools", views.ToolListView.as_view()),
]
