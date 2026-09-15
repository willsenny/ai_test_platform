"""
Executor URLs（挂载于 /api/v1/executor/）
"""
from django.urls import path

from . import views

urlpatterns = [
    path("ui/run", views.RunUITestView.as_view()),
    path("api/run", views.RunAPITestView.as_view()),
]
