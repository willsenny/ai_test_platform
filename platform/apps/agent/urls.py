"""
Agent URLs
"""
from django.urls import path
from . import views

urlpatterns = [
    path("generate", views.GenerateTestView.as_view()),
    path("heal", views.HealView.as_view()),
    path("cost", views.CostReportView.as_view()),
]
