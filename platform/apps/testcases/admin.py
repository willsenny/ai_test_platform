from django.contrib import admin

from .models import TestCase


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "kind", "test_type", "module", "project",
        "project_key", "priority", "last_run_status", "created_at",
    )
    list_filter = ("kind", "test_type", "priority", "project_key", "last_run_status")
    search_fields = ("title", "tags", "module")
