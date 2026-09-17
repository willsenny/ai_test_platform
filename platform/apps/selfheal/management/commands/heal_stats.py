"""
自愈指标（Phase J Step 6）。

用法：
    python manage.py heal_stats
"""
from django.core.management.base import BaseCommand

from apps.selfheal.models import SelfHealLog


class Command(BaseCommand):
    help = "打印自愈成功率（按 失败模式 → 修复策略）"

    def handle(self, *args, **options):
        logs = list(SelfHealLog.objects.order_by("-attempt_count"))
        if not logs:
            self.stdout.write("暂无自愈记录")
            return

        self.stdout.write(self.style.MIGRATE_HEADING("自愈指标"))
        self.stdout.write(
            f"{'failure_pattern':<22}{'fix_strategy':<20}{'success/attempt':<16}rate"
        )
        for log in logs:
            self.stdout.write(
                f"{log.failure_pattern:<22}{log.fix_strategy:<20}"
                f"{f'{log.success_count}/{log.attempt_count}':<16}"
                f"{log.success_rate:.0%}"
            )

        total = sum(log.attempt_count for log in logs)
        success = sum(log.success_count for log in logs)
        rate = success / total if total else 0.0
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"合计: {success}/{total} 成功，成功率 {rate:.0%}")
        )
