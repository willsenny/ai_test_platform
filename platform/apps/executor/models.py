"""
执行结果模型（Phase E）

把执行结果从 TestCase 中拆出来：
- TestRun:        一次执行批次（多条用例）
- TestStepResult: 每个 step / assertion 的明细，FK 回 TestCase 与 TestRun

为 Phase F 自愈提供"失败样本"数据结构。
"""
from django.db import models


class TestRun(models.Model):
    """一次执行批次"""

    class Status(models.TextChoices):
        RUNNING = "running", "运行中"
        PASS = "pass", "通过"
        FAIL = "fail", "失败"
        ERROR = "error", "异常"
        SKIPPED = "skipped", "跳过"

    project_id = models.CharField(max_length=64, db_index=True, default="")
    goal = models.CharField(max_length=500, blank=True, default="")
    source = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    total_cases = models.IntegerField(default=0)
    passed_cases = models.IntegerField(default=0)
    failed_cases = models.IntegerField(default=0)

    report_json = models.CharField(max_length=500, blank=True, default="")
    report_html = models.CharField(max_length=500, blank=True, default="")

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "执行批次"
        verbose_name_plural = "执行批次"

    def __str__(self) -> str:
        return f"TestRun #{self.pk} [{self.status}] cases={self.passed_cases}/{self.total_cases}"


class TestStepResult(models.Model):
    """单个 step / assertion 的执行明细（失败样本来源）"""

    class Status(models.TextChoices):
        PASS = "pass", "通过"
        FAIL = "fail", "失败"
        ERROR = "error", "异常"
        SKIP = "skip", "跳过"

    run = models.ForeignKey(
        TestRun, on_delete=models.CASCADE, related_name="step_results"
    )
    testcase = models.ForeignKey(
        "testcases.TestCase", on_delete=models.CASCADE, related_name="step_results"
    )
    step_index = models.IntegerField(default=0)
    phase = models.CharField(max_length=20, default="step")  # step | assert
    action = models.CharField(max_length=50, blank=True, default="")
    selector = models.CharField(max_length=500, blank=True, default="")
    value = models.TextField(blank=True, default="")
    expected = models.TextField(blank=True, default="")
    actual = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PASS
    )
    error = models.TextField(blank=True, default="")
    screenshot_path = models.CharField(max_length=500, blank=True, default="")
    duration_ms = models.IntegerField(default=0)

    class Meta:
        ordering = ["run_id", "testcase_id", "step_index"]
        verbose_name = "步骤结果"
        verbose_name_plural = "步骤结果"

    def __str__(self) -> str:
        return f"run#{self.run_id} case#{self.testcase_id} {self.phase}{self.step_index} [{self.status}]"
