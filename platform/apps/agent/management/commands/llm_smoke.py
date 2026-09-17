"""
LLM 连通性冒烟（Phase J Step 2）。

用法：
    python manage.py llm_smoke
    python manage.py llm_smoke --structured
"""
import asyncio

from django.core.management.base import BaseCommand, CommandError

from apps.agent.llm import call_llm
from apps.agent.router import route


class Command(BaseCommand):
    help = "验证 DeepSeek Flash（low/high）真实调用与结构化输出"

    def add_arguments(self, parser):
        parser.add_argument(
            "--structured", action="store_true", help="额外验证 pydantic 结构化输出"
        )
        parser.add_argument("--task", default="generate_testcase", help="路由任务类型")

    def handle(self, *args, **options):
        config = route(options["task"])
        self.stdout.write(f"model={config.model} base_url={config.base_url} reasoning={config.reasoning_effort}")

        try:
            result = asyncio.run(
                call_llm(
                    config,
                    "请用一句中文说明什么是冒烟测试。",
                    system="你是测试专家。",
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"LLM 调用失败: {type(exc).__name__}: {exc}")

        usage = result.get("usage", {})
        self.stdout.write(self.style.SUCCESS("[plain] ok"))
        self.stdout.write(f"    content = {str(result.get('content'))[:200]}")
        self.stdout.write(
            f"    usage   = in={usage.get('input_tokens')} out={usage.get('output_tokens')}"
        )

        if options["structured"]:
            from apps.agent.generation import call_structured
            from apps.agent.prompts import build_manual_prompt
            from apps.agent.schemas import ManualCaseList

            scenario = {
                "title": "手机号验证码登录",
                "goal": "使用手机号+验证码登录",
                "business_rules": ["验证码 5 分钟有效"],
                "test_data": {"手机号": "13800138000", "验证码": "123456"},
                "acceptance": [
                    {
                        "name": "正常登录",
                        "given": ["用户在登录页"],
                        "when": ["输入手机号与验证码", "点击登录"],
                        "then": ["页面提示 登录成功"],
                    }
                ],
            }
            structured, _usage, _latency = asyncio.run(
                call_structured(
                    config,
                    build_manual_prompt(scenario),
                    ManualCaseList,
                    system="你是资深测试工程师。",
                )
            )
            self.stdout.write(self.style.SUCCESS(f"[structured] cases={len(structured.cases)}"))
            for case in structured.cases:
                self.stdout.write(f"    - {case.title} steps={len(case.steps)}")
