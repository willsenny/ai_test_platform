from django.contrib import admin

from .models import Project, RequirementDoc, TestGenerationBatch


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "key", "base_url", "api_base_url", "created_at")
    search_fields = ("name", "key")


@admin.register(RequirementDoc)
class RequirementDocAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "project", "file_type", "status", "created_at")
    list_filter = ("status", "file_type", "project")
    search_fields = ("title",)
    readonly_fields = ("parsed_scenarios", "error_message")


@admin.register(TestGenerationBatch)
class TestGenerationBatchAdmin(admin.ModelAdmin):
    list_display = (
        "id", "project", "doc", "status",
        "total", "generated", "executed", "healed", "created_at",
    )
    list_filter = ("status", "project")
    readonly_fields = ("case_ids", "run", "error_message")
