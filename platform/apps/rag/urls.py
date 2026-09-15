"""
RAG URLs
"""
from django.urls import path
from . import views

urlpatterns = [
    path("ingest", views.IngestView.as_view()),
    path("retrieve", views.RetrieveView.as_view()),
]
