"""
自愈经验沉淀模型（Phase F）

按 (failure_pattern, fix_strategy) 维度累计成功/尝试次数，供后续规则权重调整。
"""
from django.db import models


class SelfHealLog(models.Model):
    """失败模式 → 修复策略 的统计"""

    failure_pattern = models.CharField(max_length=50)  # element_not_found/text_mismatch/timeout/navigation_failed
    fix_strategy = models.CharField(max_length=50)     # selector_remap/assertion_refresh/timing_wait/none
    attempt_count = models.IntegerField(default=0)
    success_count = models.IntegerField(default=0)

    last_testcase = models.ForeignKey(
        "testcases.TestCase",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="heal_logs",
    )
    last_detail = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("failure_pattern", "fix_strategy")
        ordering = ["-updated_at"]
        verbose_name = "自愈日志"
        verbose_name_plural = "自愈日志"

    @property
    def success_rate(self) -> float:
        return self.success_count / self.attempt_count if self.attempt_count else 0.0

    def __str__(self) -> str:
        return (
            f"{self.failure_pattern} → {self.fix_strategy} "
            f"({self.success_count}/{self.attempt_count})"
        )
