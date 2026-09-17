from django.contrib import admin

from .models import (
    LLMCall,
    Project,
    RequirementDoc,
    Scenario,
    TestGenerationBatch,
)


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


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = (
        "id", "story_key", "title", "project", "module",
        "priority", "sprint", "created_at",
    )
    list_filter = ("priority", "project", "sprint", "module")
    search_fields = ("story_key", "title", "module")
    readonly_fields = ("acceptance", "test_data", "business_rules", "raw_text")


@admin.register(TestGenerationBatch)
class TestGenerationBatchAdmin(admin.ModelAdmin):
    list_display = (
        "id", "project", "doc", "status",
        "total", "generated", "executed", "healed", "created_at",
    )
    list_filter = ("status", "project")
    readonly_fields = ("case_ids", "run", "error_message")


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = (
        "id", "task", "model", "reasoning",
        "input_tokens", "output_tokens", "cost_usd", "latency_ms",
        "success", "created_at",
    )
    list_filter = ("task", "model", "success")
    readonly_fields = tuple(
        f.name for f in LLMCall._meta.fields
    )
