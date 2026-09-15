from django.contrib import admin

from .models import SelfHealLog


@admin.register(SelfHealLog)
class SelfHealLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "failure_pattern",
        "fix_strategy",
        "success_count",
        "attempt_count",
        "success_rate",
        "updated_at",
    )
    list_filter = ("failure_pattern", "fix_strategy")
    search_fields = ("failure_pattern", "fix_strategy", "last_detail")

    @admin.display(description="成功率")
    def success_rate(self, obj):
        return f"{obj.success_rate:.0%}"
