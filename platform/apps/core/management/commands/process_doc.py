"""
Phase I 一键链路命令。

用法：
    python manage.py process_doc <doc_id>

链路：解析需求文档 → 批量生成用例 → 自动执行 → 自动自愈 → 生成报告。
无手动 flag：解析/生成/执行/自愈默认全开。
"""
import asyncio

from django.core.management.base import BaseCommand, CommandError

from apps.core.mock_api import start_mock_api
from apps.core.models import RequirementDoc, TestGenerationBatch
from apps.core.services.doc_service import parse_doc
from apps.core.services.generation_service import generate_from_doc


class Command(BaseCommand):
    help = "解析需求文档并一键完成 生成→执行→自愈"

    def add_arguments(self, parser):
        parser.add_argument("doc_id", type=int, help="RequirementDoc 主键")
        parser.add_argument("--project-id", default=None, help="项目 key（文档未关联项目时）")
        parser.add_argument("--api-base-url", default="", help="覆盖 API 根地址")
        parser.add_argument("--case-count", type=int, default=3, help="每场景生成用例数（UI 兜底）")
        parser.add_argument("--no-execute", action="store_true", help="仅生成不执行")
        parser.add_argument("--no-heal", action="store_true", help="执行后不触发自愈")

    def handle(self, *args, **options):
        doc_id = options["doc_id"]
        if not RequirementDoc.objects.filter(pk=doc_id).exists():
            raise CommandError(f"RequirementDoc #{doc_id} not found")

        # ---- [1] 解析 ----
        doc = parse_doc(doc_id)
        scenarios = doc.parsed_scenarios or []
        self.stdout.write(self.style.MIGRATE_HEADING("[1] parse_doc"))
        self.stdout.write(f"    doc          = #{doc.pk} {doc.title or doc.file.name}")
        self.stdout.write(f"    status       = {doc.status}")
        self.stdout.write(f"    scenarios    = {len(scenarios)}")
        for scenario in scenarios:
            self.stdout.write(
                f"      - [{scenario.get('type')}][{scenario.get('priority')}] "
                f"{scenario.get('title')}"
            )
        if doc.status == RequirementDoc.Status.FAILED:
            raise CommandError(f"parse failed: {doc.error_message}")

        # ---- 离线夹具（仅当需要且未配置时）----
        server = None
        api_base_url = options["api_base_url"]
        ui_target_url = ""
        project = doc.project
        def _wants(scenario, key):
            automation = scenario.get("automation") or {}
            if automation:
                return bool(automation.get(key))
            return scenario.get("type") == key

        swagger_url = project.swagger_url if project else ""
        if not swagger_url:
            for scenario in scenarios:
                candidate = (scenario.get("env") or {}).get("swagger")
                if candidate:
                    swagger_url = candidate
                    break

        need_api = any(_wants(s, "api") for s in scenarios) or bool(swagger_url)
        need_ui = any(_wants(s, "ui") for s in scenarios)
        if project is not None:
            if need_api and not api_base_url and not project.api_base_url:
                server, api_base_url = start_mock_api()
                self.stdout.write(f"    [mock-api] {api_base_url}")
            if need_ui and not project.base_url:
                from apps.agent.generation import default_ui_target

                ui_target_url = default_ui_target()
                self.stdout.write(f"    [ui-fixture] {ui_target_url}")

        # 离线演示：mock 同时提供公开 spec
        if server is not None:
            swagger_url = f"{api_base_url}/v3/api-docs"
            self.stdout.write(f"    [swagger-fixture] {swagger_url}")

        # ---- Swagger 导入（公开 spec，best-effort）----
        if swagger_url:
            from apps.core.services.swagger_service import import_swagger_for_doc

            base = api_base_url or (project.api_base_url if project else "")
            count = import_swagger_for_doc(doc, swagger_url, base_url=base)
            self.stdout.write(f"    [swagger] {swagger_url} -> {count} 个接口场景")

        try:
            # ---- [2-5] 生成 → 执行 → 自愈 ----
            batch = asyncio.run(
                generate_from_doc(
                    doc_id,
                    project_id=options["project_id"],
                    api_base_url=api_base_url,
                    ui_target_url=ui_target_url,
                    case_count=options["case_count"],
                    execute=not options["no_execute"],
                    self_heal=not options["no_heal"],
                )
            )
        finally:
            if server is not None:
                server.shutdown()

        self.stdout.write(self.style.MIGRATE_HEADING("[2] batch"))
        self.stdout.write(f"    batch        = #{batch.pk} [{batch.status}]")
        self.stdout.write(
            f"    counts       = total={batch.total} generated={batch.generated} "
            f"executed={batch.executed} healed={batch.healed}"
        )
        if batch.error_message:
            self.stdout.write(self.style.WARNING(f"    errors       = {batch.error_message}"))

        if batch.run_id:
            run = TestGenerationBatch.objects.select_related("run").get(pk=batch.pk).run
            self.stdout.write(
                f"    TestRun      = #{run.pk} [{run.status}] "
                f"{run.passed_cases}/{run.total_cases} passed"
            )
            self.stdout.write(f"    report html  = {run.report_html}")
            self.stdout.write(f"    report json  = {run.report_json}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"完成: parse → generate → execute → heal (batch #{batch.pk})"
        ))
