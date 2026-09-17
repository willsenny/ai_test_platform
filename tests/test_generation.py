"""Phase J Step 2：LLM 用例生成测试（不调用真实 LLM / DB）。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class TestExtractJson:
    def test_plain(self):
        from apps.agent.generation import extract_json

        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        from apps.agent.generation import extract_json

        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_surrounded(self):
        from apps.agent.generation import extract_json

        assert extract_json('说明如下：{"cases": []} 结束') == {"cases": []}


class TestSchemas:
    def test_manual_case_list(self):
        from apps.agent.schemas import ManualCaseList

        data = {
            "cases": [
                {
                    "title": "正常登录",
                    "steps": [{"action": "输入手机号", "expected": "输入成功"}],
                    "expected_result": "登录成功",
                    "priority": "P0",
                }
            ]
        }
        parsed = ManualCaseList.model_validate(data)
        assert parsed.cases[0].title == "正常登录"
        assert parsed.cases[0].steps[0].action == "输入手机号"

    def test_ui_and_api_lists_default(self):
        from apps.agent.schemas import ApiCaseList, UICaseList

        ui = UICaseList.model_validate({"cases": [{"title": "登录", "steps": []}]})
        assert ui.cases[0].assertions == []
        api = ApiCaseList.model_validate({"cases": [{"title": "接口", "path": "/api/login"}]})
        assert api.cases[0].method == "GET"


class TestPrompts:
    def test_manual_prompt_contains_story_and_gherkin(self):
        from apps.agent.prompts import build_manual_prompt

        scenario = {
            "story_key": "ACC-101",
            "title": "登录",
            "business_rules": ["验证码有效"],
            "test_data": {"手机号": "138"},
            "acceptance": [
                {"name": "正常", "given": ["在登录页"], "when": ["输入"], "then": ["成功"]}
            ],
        }
        prompt = build_manual_prompt(scenario)
        assert "ACC-101" in prompt
        assert "Given 在登录页" in prompt
        assert "Then 成功" in prompt

    def test_ui_prompt_includes_target(self):
        from apps.agent.prompts import build_ui_prompt

        prompt = build_ui_prompt({"title": "登录"}, "http://demo/login")
        assert "http://demo/login" in prompt


class TestAutomationAndNormalize:
    def test_resolve_automation_explicit(self):
        from apps.agent.generation import resolve_automation

        assert resolve_automation(
            {"automation": {"manual": True, "ui": False, "api": True}}
        ) == {"manual": True, "ui": False, "api": True}

    def test_resolve_automation_from_type(self):
        from apps.agent.generation import resolve_automation

        assert resolve_automation({"type": "api"}) == {
            "manual": True, "ui": False, "api": True
        }

    def test_normalize_api_builds_request_and_url(self):
        from apps.agent.generation import _normalize
        from apps.agent.schemas import ApiCase

        case = ApiCase(title="登录接口", method="post", path="/api/login", body={"phone": "1"})
        out = _normalize("api", case, {"env": {"api": "http://host/api"}}, 7, "登录")
        assert out["kind"] == "automated"
        assert out["test_type"] == "api"
        assert out["steps"][0]["action"] == "request"
        assert out["steps"][0]["method"] == "POST"
        assert out["steps"][0]["url"] == "http://host/api/api/login"
        assert out["scenario_id"] == 7

    def test_normalize_ui_fills_goto(self):
        from apps.agent.generation import _normalize
        from apps.agent.schemas import UICase

        case = UICase(title="打开", steps=[{"action": "goto", "selector": "", "value": ""}])
        out = _normalize("ui", case, {}, None, "m")
        assert out["test_type"] == "ui"
        assert out["steps"][0]["value"]
        assert out["scenario_id"] is None


class TestDedup:
    def test_removes_duplicates(self):
        from apps.agent.generation import dedup

        case = {"kind": "automated", "test_type": "ui", "title": "A", "steps": [{"action": "click"}]}
        assert len(dedup([case, dict(case)])) == 1

    def test_keeps_distinct(self):
        from apps.agent.generation import dedup

        a = {"kind": "manual", "test_type": "functional", "title": "A"}
        b = {"kind": "automated", "test_type": "ui", "title": "A"}
        assert len(dedup([a, b])) == 2


class TestCallStructured:
    @pytest.mark.asyncio
    async def test_validates_and_repairs(self, monkeypatch):
        from apps.agent import generation
        from apps.agent.schemas import ManualCaseList

        good = '{"cases":[{"title":"t","steps":[],"priority":"P0"}]}'
        calls = {"n": 0}

        async def fake_call(config, prompt, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": "not json", "usage": {"input_tokens": 1, "output_tokens": 1}}
            return {"content": good, "usage": {"input_tokens": 2, "output_tokens": 2}}

        monkeypatch.setattr(generation, "call_llm", fake_call)
        config = SimpleNamespace(model="deepseek-flash", reasoning_effort=None)
        parsed, usage, _latency = await generation.call_structured(
            config, "prompt", ManualCaseList, system="s"
        )
        assert parsed.cases[0].title == "t"
        assert usage["input_tokens"] == 3


class TestGenerateForScenario:
    @pytest.mark.asyncio
    async def test_generates_requested_kinds(self, monkeypatch):
        from apps.agent import generation
        from apps.agent.schemas import ApiCaseList, ManualCaseList, UICaseList

        monkeypatch.setattr(
            generation, "route",
            lambda task: SimpleNamespace(model="deepseek-flash", reasoning_effort=None),
        )
        generation.record_llm_call = AsyncMock()

        async def fake_structured(config, prompt, schema, **kwargs):
            if schema is ManualCaseList:
                return schema.model_validate({"cases": [{"title": "手动"}]}), {}, 0
            if schema is UICaseList:
                return schema.model_validate({"cases": [{"title": "UI", "steps": []}]}), {}, 0
            return schema.model_validate({"cases": [{"title": "API", "path": "/x"}]}), {}, 0

        monkeypatch.setattr(generation, "call_structured", fake_structured)

        cases = await generation.generate_for_scenario(
            {
                "title": "登录",
                "automation": {"manual": True, "ui": True, "api": True},
                "env": {"api": "http://host"},
                "priority": "P0",
            }
        )
        kinds = sorted((c["kind"], c["test_type"]) for c in cases)
        assert ("manual", "functional") in kinds
        assert ("automated", "ui") in kinds
        assert ("automated", "api") in kinds
