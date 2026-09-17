from django.contrib import admin

from .models import TestCase


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "project", "project_key", "priority",
        "last_run_status", "last_run_at", "created_at",
    )
    list_filter = ("priority", "project_key", "last_run_status")
    search_fields = ("title", "tags")
