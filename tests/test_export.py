"""Phase J Step 5：归档导出测试（纯函数 + 文件产物，不依赖 DB）。"""
import json
import zipfile
from types import SimpleNamespace


def _manual_case():
    return SimpleNamespace(
        pk=1, title="正常登录", kind="manual", test_type="functional",
        module="登录", priority="P0", preconditions=["已注册"],
        steps=[], manual_steps=[{"action": "输入手机号", "expected": "输入成功"}],
        expected_result="登录成功", assertions=[], tags=["smoke"],
        target_url="", source="doc:batch",
    )


def _ui_case():
    return SimpleNamespace(
        pk=2, title="UI 登录", kind="automated", test_type="ui",
        module="登录", priority="P0", preconditions=[], manual_steps=[],
        expected_result="", tags=[], source="doc:batch",
        target_url="http://x", steps=[
            {"action": "goto", "selector": "", "value": "http://x"},
            {"action": "click", "selector": 'button:has-text("登录")', "value": ""},
        ],
        assertions=[{"type": "text_contains", "selector": 'text="登录成功"', "expected": "登录成功"}],
    )


def _api_case():
    return SimpleNamespace(
        pk=3, title="接口登录", kind="automated", test_type="api",
        module="登录", priority="P0", preconditions=[], manual_steps=[],
        expected_result="", tags=[], source="doc:batch", target_url="http://x/login",
        steps=[{"action": "request", "method": "POST", "url": "http://x/login",
                "headers": {"Content-Type": "application/json"}, "body": {"phone": "1"}, "params": {}}],
        assertions=[{"type": "status_equals", "expected": 200},
                    {"type": "json_field", "path": "code", "expected": 0}],
    )


def _batch():
    return SimpleNamespace(
        pk=9, project_id=1, doc_id=2, project=SimpleNamespace(key="demo"),
        status="done", total=2, generated=3, executed=3, healed=0,
    )


class TestSafeName:
    def test_sanitize(self):
        from apps.core.services.export_service import safe_name

        assert safe_name("正常登录 #1") == "正常登录_1"
        assert safe_name("", fallback="case") == "case"


class TestManualRows:
    def test_formats_manual_steps(self):
        from apps.core.services.export_service import manual_rows

        rows = manual_rows([_manual_case()])
        assert rows[0][0] == 1
        assert "输入手机号" in rows[0][6]
        assert rows[0][7] == "登录成功"


class TestRenderedTests:
    def test_api_tests(self):
        from apps.core.services.export_service import render_api_tests

        code = render_api_tests([_api_case()])
        assert "httpx.request" in code
        assert "assert resp.status_code == 200" in code
        assert "_json_path(resp.json(), \"code\")" in code

    def test_ui_tests(self):
        from apps.core.services.export_service import render_ui_tests

        code = render_ui_tests([_ui_case()])
        assert "page.goto" in code
        assert "page.click" in code
        assert "in page.inner_text" in code


class TestArtifacts:
    def test_xlsx(self, tmp_path):
        from apps.core.services.export_service import build_xlsx

        path = tmp_path / "manual.xlsx"
        build_xlsx([_manual_case()], path)
        assert path.exists() and path.stat().st_size > 0

    def test_pytest_zip(self, tmp_path):
        from apps.core.services.export_service import build_pytest_zip

        path = tmp_path / "auto.zip"
        build_pytest_zip(_batch(), [_ui_case(), _api_case()], path)
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            assert {
                "conftest.py", "test_ui_generated.py",
                "test_api_generated.py", "requirements.txt",
                "README.md", "manifest.json",
            } <= names
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["ui_cases"] == [2]
            assert manifest["api_cases"] == [3]

    def test_json(self, tmp_path):
        from apps.core.services.export_service import build_json

        path = tmp_path / "archive.json"
        build_json(_batch(), [_manual_case(), _ui_case(), _api_case()], path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["batch"]["id"] == 9
        assert len(payload["cases"]) == 3
        assert payload["cases"][1]["kind"] == "automated"
