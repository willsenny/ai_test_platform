"""
项目管理（沿用 WHartTest 的 Project 概念）

一个 Project 对应一个被测系统，用于隔离用例库与 RAG 知识库。
Phase I：新增需求文档（RequirementDoc）与批量生成批次（TestGenerationBatch），
打通「上传需求 → 解析场景 → 批量生成 → 执行 → 自愈」链路。
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

    # Phase I：被测系统地址（UI / API / 接口规范）
    base_url = models.CharField(
        max_length=500, blank=True, default="", help_text="被测 Web 系统地址"
    )
    api_base_url = models.CharField(
        max_length=500, blank=True, default="", help_text="被测 API 根地址"
    )
    swagger_url = models.CharField(
        max_length=500, blank=True, default="", help_text="Swagger/OpenAPI 地址"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "项目"
        verbose_name_plural = "项目"

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"


class RequirementDoc(models.Model):
    """需求文档：上传 → 解析为结构化场景。"""

    class Status(models.TextChoices):
        PENDING = "pending", "待解析"
        PARSING = "parsing", "解析中"
        PARSED = "parsed", "已解析"
        GENERATING = "generating", "生成中"
        DONE = "done", "已完成"
        FAILED = "failed", "失败"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="requirements"
    )
    title = models.CharField(max_length=300, blank=True, default="")
    file = models.FileField(upload_to="requirements/")
    file_type = models.CharField(max_length=20, blank=True, default="")
    parsed_scenarios = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "需求文档"
        verbose_name_plural = "需求文档"

    def __str__(self) -> str:
        return self.title or f"RequirementDoc #{self.pk}"

    @property
    def scenario_count(self) -> int:
        return len(self.parsed_scenarios or [])


class TestGenerationBatch(models.Model):
    """一次批量生成/执行/自愈批次，记录全链路进度。"""

    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        GENERATING = "generating", "生成中"
        EXECUTING = "executing", "执行中"
        HEALING = "healing", "自愈中"
        DONE = "done", "已完成"
        FAILED = "failed", "失败"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="generation_batches"
    )
    doc = models.ForeignKey(
        RequirementDoc, on_delete=models.CASCADE, related_name="batches"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    total = models.PositiveIntegerField(default=0)
    generated = models.PositiveIntegerField(default=0)
    executed = models.PositiveIntegerField(default=0)
    healed = models.PositiveIntegerField(default=0)

    run = models.ForeignKey(
        "executor.TestRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generation_batches",
    )
    case_ids = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "生成批次"
        verbose_name_plural = "生成批次"

    def __str__(self) -> str:
        return f"Batch #{self.pk} [{self.status}] {self.generated}/{self.total}"

    @property
    def progress_percent(self) -> int:
        if not self.total:
            return 0
        if self.status == self.Status.DONE:
            return 100
        done = min(self.generated, self.total)
        return int(done / self.total * 100)
