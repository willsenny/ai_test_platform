"""
用例库（字段对齐 apps.agent.state.TestCase，便于 LangGraph 直接落库）

steps 结构: [{"action": "...", "input": "...", "expected": "..."}]
"""
from django.db import models


class TestCase(models.Model):
    """结构化测试用例"""

    class Priority(models.TextChoices):
        P0 = "P0", "P0 - 冒烟/核心"
        P1 = "P1", "P1 - 主要功能"
        P2 = "P2", "P2 - 次要/边界"

    project_id = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=300)
    preconditions = models.JSONField(default=list, blank=True)
    steps = models.JSONField(default=list, blank=True)
    assertions = models.JSONField(default=list, blank=True)
    priority = models.CharField(
        max_length=2, choices=Priority.choices, default=Priority.P1
    )
    tags = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "测试用例"
        verbose_name_plural = "测试用例"

    def __str__(self) -> str:
        return f"[{self.priority}] {self.title}"
