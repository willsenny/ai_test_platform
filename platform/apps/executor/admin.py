"""
执行结果 Admin（Phase E）

按批次查看 TestRun，并内联展示每个 step / assertion 的明细。
"""
import os

from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html

from .models import TestRun, TestStepResult


class TestStepResultInline(admin.TabularInline):
    model = TestStepResult
    extra = 0
    can_delete = False
    ordering = ("testcase_id", "step_index", "phase")
    fields = (
        "testcase",
        "step_index",
        "phase",
        "action",
        "selector",
        "expected",
        "actual",
        "status",
        "error",
        "duration_ms",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TestRun)
class TestRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "project_id",
        "goal",
        "passed_cases",
        "total_cases",
        "started_at",
        "finished_at",
        "report_link",
    )
    list_filter = ("status", "project_id", "source")
    search_fields = ("goal", "project_id", "source")
    readonly_fields = ("started_at", "finished_at", "report_json", "report_html")
    inlines = [TestStepResultInline]

    @admin.display(description="报告")
    def report_link(self, obj):
        if not obj.report_html:
            return "-"
        filename = os.path.basename(obj.report_html)
        url = f"{settings.MEDIA_URL}reports/{filename}"
        path = os.path.basename(obj.report_json) if obj.report_json else ""
        json_link = (
            format_html(' &nbsp;<a href="{}reports/{}" target="_blank">JSON</a>', settings.MEDIA_URL, path)
            if path
            else ""
        )
        return format_html(
            '<a href="{}" target="_blank">HTML</a>{}', url, json_link
        )


@admin.register(TestStepResult)
class TestStepResultAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "run",
        "testcase",
        "step_index",
        "phase",
        "action",
        "selector",
        "status",
        "duration_ms",
    )
    list_filter = ("status", "phase")
    search_fields = ("selector", "action", "actual", "error")
