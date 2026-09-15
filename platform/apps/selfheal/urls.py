"""
SelfHeal URLs（挂载于 /api/v1/selfheal/）
"""
from django.urls import path

from . import views

urlpatterns = [
    path("heal", views.SelfHealView.as_view()),
]
