"""
项目管理（沿用 WHartTest 的 Project 概念）

一个 Project 对应一个被测系统，用于隔离用例库与 RAG 知识库。
"""
from django.db import models


class Project(models.Model):
    """测试项目"""

    name = models.CharField(max_length=200)
    key = models.SlugField(
        max_length=64,
        unique=True,
        help_text="项目唯一标识，用于 project_id 隔离",
    )
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "项目"
        verbose_name_plural = "项目"

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"
