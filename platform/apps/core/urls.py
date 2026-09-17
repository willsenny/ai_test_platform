"""
Project URLs

API（挂载于 /api/v1/projects/）: DRF router
Web（挂载于站点根）: web_urlpatterns
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    BatchDetailView,
    BatchExportView,
    BatchRunView,
    DocDetailView,
    DocUploadView,
    ProjectListView,
    ProjectViewSet,
    ReportView,
    ScenarioEditView,
)

router = DefaultRouter()
router.register("", ProjectViewSet, basename="project")

urlpatterns = router.urls

web_urlpatterns = [
    path("", ProjectListView.as_view(), name="web-projects"),
    path("docs/upload/", DocUploadView.as_view(), name="web-doc-upload"),
    path("docs/<int:pk>/", DocDetailView.as_view(), name="web-doc-detail"),
    path(
        "scenarios/<int:pk>/edit/",
        ScenarioEditView.as_view(),
        name="web-scenario-edit",
    ),
    path("batches/<int:pk>/", BatchDetailView.as_view(), name="web-batch-detail"),
    path("batches/<int:pk>/report/", ReportView.as_view(), name="web-batch-report"),
    path("batches/<int:pk>/run/", BatchRunView.as_view(), name="web-batch-run"),
    path(
        "batches/<int:pk>/export/<str:fmt>/",
        BatchExportView.as_view(),
        name="web-batch-export",
    ),
]
