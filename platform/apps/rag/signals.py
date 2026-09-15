"""
Phase G 向量写入信号

- TestCase       保存 → 索引到 testcases
- TestStepResult 失败态保存 → 索引到 step_results（bulk_create 不触发，见 executor 显式调用）
- SelfHealLog    保存 → 索引到 heal_logs

全部 best-effort，Qdrant 不可用不影响主流程。
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="testcases.TestCase")
def _on_testcase_saved(sender, instance, **kwargs):
    from .indexer import schedule_testcase

    transaction.on_commit(lambda: schedule_testcase(instance))


@receiver(post_save, sender="executor.TestStepResult")
def _on_step_result_saved(sender, instance, **kwargs):
    if instance.status not in ("fail", "error"):
        return
    from .indexer import schedule_failure

    transaction.on_commit(lambda: schedule_failure(instance))


@receiver(post_save, sender="selfheal.SelfHealLog")
def _on_heal_log_saved(sender, instance, **kwargs):
    from .indexer import schedule_heal_log

    transaction.on_commit(lambda: schedule_heal_log(instance))
