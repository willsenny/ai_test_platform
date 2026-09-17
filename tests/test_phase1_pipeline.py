"""
Phase I 产品化链路测试（纯 Python 部分，不依赖 DB）。

覆盖：
- Markdown 解析器：场景数量、ui/api 分类、优先级/标签/验收标准、API 规格
- 解析器工厂：文件类型归一化与不支持类型
- 生成图 / 完整图编译
- executor JSON 路径断言工具
"""
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_requirements.md"
REPO_ROOT = Path(__file__).resolve().parent.parent


class TestMarkdownParser:
    def _scenarios(self):
        from apps.core.parsers import get_parser

        text = FIXTURE.read_text(encoding="utf-8")
        return get_parser("md").parse(text)

    def test_extracts_at_least_three_scenarios(self):
        scenarios = self._scenarios()
        assert len(scenarios) >= 3

    def test_ui_and_api_classification(self):
        scenarios = self._scenarios()
        types = {s["type"] for s in scenarios}
        assert types == {"ui", "api"}
        api = [s for s in scenarios if s["type"] == "api"][0]
        assert api["api"]["method"] == "POST"
        assert api["api"]["path"] == "/api/login"

    def test_metadata(self):
        scenarios = self._scenarios()
        first = scenarios[0]
        assert first["priority"] == "P0"
        assert "login" in first["tags"]
        assert first["acceptance_criteria"]
        assert "ui" in first["tags"]

    def test_ui_spec_steps_extracted(self):
        scenarios = self._scenarios()
        ui_spec = [s for s in scenarios if s.get("spec", {}).get("steps")]
        assert ui_spec
        steps = ui_spec[0]["spec"]["steps"]
        assert any(s.get("selector") == "#code_old" for s in steps)


class TestParserFactory:
    def test_supported_aliases(self):
        from apps.core.parsers import get_parser

        for alias in ("md", "markdown", ".md", "file.md", "text/markdown"):
            assert get_parser(alias).__class__.__name__ == "MarkdownParser"

    def test_unsupported_raises(self):
        from apps.core.parsers import get_parser

        with pytest.raises(ValueError):
            get_parser("pdf")


class TestGraphs:
    def test_generation_graph_compiles(self):
        from apps.agent.graph import build_generation_graph

        assert build_generation_graph() is not None

    def test_full_graph_compiles(self):
        from apps.agent.graph import build_full_graph

        assert build_full_graph() is not None


class TestApiAssertionHelpers:
    def test_json_path_get(self):
        from apps.executor.executor import _json_path_get

        body = {"code": 0, "data": {"token": "abc"}, "items": [{"id": 7}]}
        assert _json_path_get(body, "code") == 0
        assert _json_path_get(body, "$.data.token") == "abc"
        assert _json_path_get(body, "items[0].id") == 7
        assert _json_path_get(body, "missing") is None

    def test_run_api_assertions_pass_and_fail(self):
        from apps.executor.executor import _run_api_assertions

        class _Case:
            pk = 1

        responses = [{"status_code": 200, "body": {"code": 0}}]
        rows, logs = [], []

        outcome = _run_api_assertions(
            _Case(), 1,
            [
                {"type": "status_equals", "expected": 200},
                {"type": "json_field", "path": "code", "expected": 0},
            ],
            responses, rows, logs, 1,
        )
        assert outcome == "pass"

        rows, logs = [], []
        outcome = _run_api_assertions(
            _Case(), 1,
            [{"type": "status_equals", "expected": 500}],
            responses, rows, logs, 1,
        )
        assert outcome == "fail"


class TestApiMcpServer:
    def test_send_request_tool_defined(self):
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from mcp_servers import api_server
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"api_server import failed: {exc}")
        assert callable(getattr(api_server, "send_request", None))
