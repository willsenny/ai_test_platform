"""
导出批次用例（Phase J Step 5）。

用法：
    python manage.py export_cases <batch_id> --format xlsx
    python manage.py export_cases <batch_id> --format pytest
    python manage.py export_cases <batch_id> --format json
    python manage.py export_cases <batch_id>            # 三种全导
"""
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import TestGenerationBatch
from apps.core.services.export_service import export_batch

_FORMATS = ("xlsx", "pytest", "json")


class Command(BaseCommand):
    help = "导出批次的 手动用例 Excel / 自动化 pytest 工程 / JSON 存档"

    def add_arguments(self, parser):
        parser.add_argument("batch_id", type=int)
        parser.add_argument(
            "--format", choices=_FORMATS + ("all",), default="all"
        )

    def handle(self, *args, **options):
        batch_id = options["batch_id"]
        if not TestGenerationBatch.objects.filter(pk=batch_id).exists():
            raise CommandError(f"TestGenerationBatch #{batch_id} not found")

        formats = _FORMATS if options["format"] == "all" else (options["format"],)
        self.stdout.write(self.style.MIGRATE_HEADING(f"export batch #{batch_id}"))
        for fmt in formats:
            job = export_batch(batch_id, fmt)
            if job.status == "done":
                self.stdout.write(self.style.SUCCESS(f"  [{fmt}] {job.file}"))
            else:
                self.stdout.write(self.style.ERROR(f"  [{fmt}] failed: {job.error}"))
