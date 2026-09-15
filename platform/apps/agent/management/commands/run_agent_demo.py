"""
最小闭环演示命令（Phase C–F）

用法:
    python manage.py run_agent_demo --goal "用户登录：手机号+验证码"
    python manage.py run_agent_demo --goal "..." --count 3 --execute
    python manage.py run_agent_demo --goal "..." --execute --self-heal \
        --inject-failure selector

链路: Django → LangGraph → MCP(stdio) → PostgreSQL
"""
import asyncio

from django.core.management.base import BaseCommand

from apps.agent.graph import run_agent_demo_workflow


class Command(BaseCommand):
    help = "运行最小闭环：planner → generator(MCP) → reporter(DB) → executor → healer"

    def add_arguments(self, parser):
        parser.add_argument("--goal", required=True, help="测试目标（需求文本）")
        parser.add_argument("--project-id", default="demo", help="项目标识")
        parser.add_argument("--count", type=int, default=3, help="生成用例数量")
        parser.add_argument(
            "--execute",
            action="store_true",
            help="生成后通过 Playwright MCP 真执行并回写结果",
        )
        parser.add_argument(
            "--self-heal",
            action="store_true",
            help="执行失败后自动触发规则自愈",
        )
        parser.add_argument(
            "--inject-failure",
            choices=["none", "selector", "assertion", "timing"],
            default="none",
            help="演示用：人为注入失败类型",
        )

    def handle(self, *args, **options):
        goal = options["goal"]
        project_id = options["project_id"]
        count = options["count"]
        execute = options["execute"]
        self_heal = options["self_heal"]
        inject_failure = options["inject_failure"]

        self.stdout.write(self.style.MIGRATE_HEADING("=== run_agent_demo ==="))
        self.stdout.write(f"goal           = {goal}")
        self.stdout.write(f"project_id     = {project_id}")
        self.stdout.write(f"count          = {count}")
        self.stdout.write(f"execute        = {execute}")
        self.stdout.write(f"self_heal      = {self_heal}")
        self.stdout.write(f"inject_failure = {inject_failure}")

        result = asyncio.run(
            run_agent_demo_workflow(
                goal=goal,
                project_id=project_id,
                count=count,
                execute=execute,
                self_heal=self_heal,
                inject_failure=inject_failure,
            )
        )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("[1] planner 计划:"))
        for line in result.get("plan", []):
            self.stdout.write(f"    {line}")
        retrieved_cases = result.get("retrieved_cases", [])
        if retrieved_cases:
            self.stdout.write(
                f"    历史用例 few-shot: {len(retrieved_cases)} 条 -> "
                f"{[c.get('payload', {}).get('title', '?') for c in retrieved_cases]}"
            )

        test_cases = result.get("test_cases", [])
        self.stdout.write(self.style.MIGRATE_HEADING(f"[2] generator 生成 {len(test_cases)} 条用例:"))
        for case in test_cases:
            self.stdout.write(f"    - [{case['priority']}] {case['title']}")

        self.stdout.write(self.style.MIGRATE_HEADING("[3] reporter 入库:"))
        self.stdout.write(f"    saved_ids = {result.get('saved_ids', [])}")

        if execute:
            results = result.get("execution_results", [])
            run_id = result.get("execution_run_id")
            report = result.get("execution_report", {})
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"[4] executor 真执行 {len(results)} 条 (TestRun #{run_id}):"
                )
            )
            for run in results:
                self.stdout.write(f"    --- case {run['case_id']}: {run['status']} ---")
                for line in run.get("log", "").splitlines():
                    self.stdout.write(f"        {line}")

            passed = sum(1 for r in results if r["status"] == "pass")
            self.stdout.write(f"    汇总: {passed}/{len(results)} pass")
            if report:
                self.stdout.write(f"    报告 HTML: {report.get('html')}")
                self.stdout.write(f"    报告 JSON: {report.get('json')}")

        if self_heal:
            heal_results = result.get("heal_results", [])
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"[5] healer 自愈 {len(heal_results)} 条失败用例:"
                )
            )
            for heal in heal_results:
                self.stdout.write(
                    f"    --- case {heal['case_id']}: "
                    f"healed={heal['healed']} failures={heal['failure_count']} ---"
                )
                for attempt in heal.get("attempts", []):
                    self.stdout.write(
                        f"        [{attempt['failure_type']} / {attempt['suspect']}] "
                        f"strategy={attempt['strategy']} "
                        f"{attempt['old_value']!r} -> {attempt['new_value']!r} "
                        f"rerun={attempt['status_after']} healed={attempt['healed']}"
                    )
                    self.stdout.write(f"          {attempt['detail']}")
                    rag_failures = attempt.get("rag_failures") or []
                    if rag_failures:
                        self.stdout.write(
                            f"          [retrieved {len(rag_failures)} similar failures]"
                        )
                    if attempt.get("rag_hint"):
                        self.stdout.write(f"          [heal experience] {attempt['rag_hint']}")

        from apps.testcases.models import TestCase

        total = TestCase.objects.filter(source="agent:run_agent_demo").count()
        self.stdout.write(f"    DB rows (source=agent:run_agent_demo) = {total}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"✅ 完成，final_status={result.get('final_status')}"
        ))
