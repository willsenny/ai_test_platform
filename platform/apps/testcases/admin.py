from django.contrib import admin

from .models import TestCase


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "project_id", "priority", "created_at")
    list_filter = ("priority", "project_id")
    search_fields = ("title", "tags")
