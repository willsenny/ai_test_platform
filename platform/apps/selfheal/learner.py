"""
经验沉淀（Phase F · 规则驱动）

把 (failure_pattern, fix_strategy) 的尝试/成功次数累加到 SelfHealLog，
供后续规则权重调整使用。
"""


def record(
    failure_pattern: str,
    fix_strategy: str,
    success: bool,
    *,
    testcase_id: int | None = None,
    detail: str = "",
) -> dict:
    from .models import SelfHealLog

    obj, _ = SelfHealLog.objects.get_or_create(
        failure_pattern=failure_pattern or "unknown",
        fix_strategy=fix_strategy or "none",
    )
    obj.attempt_count += 1
    if success:
        obj.success_count += 1
    if testcase_id is not None:
        obj.last_testcase_id = testcase_id
    obj.last_detail = detail
    obj.save()

    return {
        "failure_pattern": obj.failure_pattern,
        "fix_strategy": obj.fix_strategy,
        "attempt_count": obj.attempt_count,
        "success_count": obj.success_count,
        "success_rate": obj.success_rate,
    }
