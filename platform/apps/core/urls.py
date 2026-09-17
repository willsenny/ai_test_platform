"""
Project URLs

API（挂载于 /api/v1/projects/）: DRF router
Web（挂载于站点根）: web_urlpatterns
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    BatchDetailView,
    DocUploadView,
    ProjectListView,
    ProjectViewSet,
    ReportView,
)

router = DefaultRouter()
router.register("", ProjectViewSet, basename="project")

urlpatterns = router.urls

web_urlpatterns = [
    path("", ProjectListView.as_view(), name="web-projects"),
    path("docs/upload/", DocUploadView.as_view(), name="web-doc-upload"),
    path("batches/<int:pk>/", BatchDetailView.as_view(), name="web-batch-detail"),
    path("batches/<int:pk>/report/", ReportView.as_view(), name="web-batch-report"),
]
