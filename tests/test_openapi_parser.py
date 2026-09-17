"""Phase J Step 3：OpenAPI 解析与 Swagger 接口用例生成测试。"""
import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "openapi_sample.json"


def _spec():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestOpenApiParser:
    def test_is_openapi_and_base_url(self):
        from apps.core.parsers.openapi_parser import base_url_from_spec, is_openapi

        spec = _spec()
        assert is_openapi(spec) is True
        assert base_url_from_spec(spec) == "http://localhost:8000/api"

    def test_parse_endpoints(self):
        from apps.core.parsers.openapi_parser import parse_endpoints

        endpoints = parse_endpoints(_spec())
        assert len(endpoints) == 2
        login = next(e for e in endpoints if e["path"] == "/login")
        assert login["method"] == "POST"
        assert login["body_required"] == ["phone", "code"]
        assert login["success_code"] == 200

    def test_resolve_refs(self):
        from apps.core.parsers.openapi_parser import example_from_schema, parse_endpoints

        login = next(e for e in parse_endpoints(_spec()) if e["path"] == "/login")
        example = example_from_schema(login["body_schema"])
        assert example == {"phone": "13800138000", "code": "123456"}

    def test_endpoint_scenarios_positive_negative_boundary(self):
        from apps.core.parsers.openapi_parser import (
            endpoints_to_scenarios,
            parse_endpoints,
        )

        scenarios = endpoints_to_scenarios(
            parse_endpoints(_spec()), "http://localhost:8000/api"
        )
        login = [s for s in scenarios if s["api"]["path"] == "/login"]
        assert len(login) == 3

        positive = next(s for s in login if "正常" in s["title"])
        types = [a["type"] for a in positive["api"]["assertions"]]
        assert "status_equals" in types
        assert "json_schema" in types
        assert positive["api"]["body"]["phone"] == "13800138000"

        negative = next(s for s in login if "缺少必填字段" in s["title"])
        assert negative["api"]["assertions"][0]["expected"] == 400
        assert "phone" not in negative["api"]["body"]

        boundary = next(s for s in login if "边界值" in s["title"])
        assert len(boundary["api"]["body"]["code"]) == 7

    def test_all_scenarios_are_api_automation(self):
        from apps.core.parsers.openapi_parser import (
            endpoints_to_scenarios,
            parse_endpoints,
        )

        scenarios = endpoints_to_scenarios(parse_endpoints(_spec()))
        assert len(scenarios) == 4
        for scenario in scenarios:
            assert scenario["type"] == "api"
            assert scenario["source"] == "swagger"
            assert scenario["automation"] == {"manual": False, "ui": False, "api": True}


class TestSwaggerCaseGeneration:
    def test_deterministic_api_case_with_base_override(self):
        from apps.agent.generation import _api_cases_from_spec
        from apps.core.parsers.openapi_parser import (
            endpoints_to_scenarios,
            parse_endpoints,
        )

        scenarios = endpoints_to_scenarios(parse_endpoints(_spec()))
        positive = next(
            s for s in scenarios
            if s["api"]["path"] == "/login" and "正常" in s["title"]
        )
        positive["scenario_id"] = 42

        cases = _api_cases_from_spec(positive, api_base_url="http://mock:1234")
        assert len(cases) == 1
        case = cases[0]
        assert case["test_type"] == "api"
        assert case["scenario_id"] == 42
        step = case["steps"][0]
        assert step["action"] == "request"
        assert step["method"] == "POST"
        assert step["url"] == "http://mock:1234/login"
        assert any(a["type"] == "json_schema" for a in case["assertions"])


class TestJsonSchemaAssertion:
    def _run(self, schema, body):
        from apps.executor.executor import _run_api_assertions

        class _Case:
            pk = 1

        rows, logs = [], []
        outcome = _run_api_assertions(
            _Case(), 1,
            [{"type": "json_schema", "schema": schema}],
            [{"status_code": 200, "body": body}],
            rows, logs, 0,
        )
        return outcome

    def test_schema_pass(self):
        schema = {
            "type": "object",
            "required": ["code"],
            "properties": {"code": {"type": "integer"}},
        }
        assert self._run(schema, {"code": 0}) == "pass"

    def test_schema_fail(self):
        schema = {
            "type": "object",
            "required": ["token"],
            "properties": {"token": {"type": "string"}},
        }
        assert self._run(schema, {"code": 0}) == "fail"
