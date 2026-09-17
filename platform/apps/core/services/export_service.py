"""
用例归档与导出（Phase J Step 5）。

- xlsx  : 手动用例 Excel（openpyxl）
- pytest: 自动化用例 pytest 工程 zip（UI=playwright, API=httpx）
- json  : 全量 JSON 存档（用例 + 执行批次）
"""
import json
import re
import time
import zipfile
from pathlib import Path

from django.conf import settings

_EXT = {"xlsx": "xlsx", "pytest": "zip", "json": "json"}


def exports_dir() -> Path:
    out = Path(settings.MEDIA_ROOT) / "exports"
    out.mkdir(parents=True, exist_ok=True)
    return out


def safe_name(text: str, fallback: str = "case") -> str:
    value = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "_", text or "").strip("_")
    return value[:40] or fallback


def _case_dict(case) -> dict:
    return {
        "id": case.pk,
        "title": case.title,
        "kind": case.kind,
        "test_type": case.test_type,
        "module": case.module,
        "priority": case.priority,
        "preconditions": list(case.preconditions or []),
        "steps": list(case.steps or []),
        "manual_steps": list(case.manual_steps or []),
        "expected_result": case.expected_result,
        "assertions": list(case.assertions or []),
        "tags": list(case.tags or []),
        "target_url": case.target_url,
        "source": case.source,
    }


def manual_rows(cases: list) -> list[list]:
    rows = []
    for case in cases:
        steps = case.manual_steps or []
        if steps:
            step_text = "\n".join(
                f"{i}. {s.get('action', '')}"
                + (f" → {s.get('expected')}" if s.get("expected") else "")
                for i, s in enumerate(steps, 1)
            )
        else:
            step_text = "\n".join(
                f"{i}. {s.get('action', '')} {s.get('selector', '')} {s.get('value', '')}".strip()
                for i, s in enumerate(case.steps or [], 1)
            )
        rows.append(
            [
                case.pk,
                case.module,
                case.title,
                case.test_type,
                case.priority,
                "\n".join(case.preconditions or []),
                step_text,
                case.expected_result,
                ", ".join(case.tags or []),
            ]
        )
    return rows


def build_xlsx(cases: list, path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "手动用例"
    headers = [
        "用例ID", "模块", "标题", "类型", "优先级",
        "前置条件", "操作步骤", "预期结果", "标签",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in manual_rows(cases):
        sheet.append(row)
    widths = [8, 16, 40, 10, 8, 24, 50, 30, 18]
    for idx, width in enumerate(widths, 1):
        sheet.column_dimensions[chr(64 + idx)].width = width
    workbook.save(path)
    return path


# ============================================================
# pytest 工程
# ============================================================
_CONFTEST = '''"""自动生成的测试工程（Phase J）。"""
import json


def _json_path(obj, path):
    if obj is None or not path:
        return None
    parts = [p for p in str(path).lstrip("$").replace("[", ".").replace("]", "").split(".") if p]
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current
'''


def _func_name(index: int, title: str) -> str:
    return f"test_{index:03d}_{safe_name(title)}"


def render_api_tests(cases: list) -> str:
    lines = [
        '"""自动生成的接口测试（httpx）。"""',
        "import jsonschema",
        "import httpx",
        "import pytest",
        "",
        "from conftest import _json_path",
        "",
    ]
    for idx, case in enumerate(cases, 1):
        lines.append(f"def {_func_name(idx, case.title)}():")
        lines.append(f'    """{case.title}"""')
        lines.append("    resp = None")
        for step in case.steps or []:
            if step.get("action") != "request":
                continue
            method = (step.get("method") or "GET").upper()
            url = step.get("url") or case.target_url
            kwargs = []
            if step.get("headers"):
                kwargs.append(f"headers={json.dumps(step['headers'], ensure_ascii=False)}")
            if step.get("body"):
                kwargs.append(f"json={json.dumps(step['body'], ensure_ascii=False)}")
            if step.get("params"):
                kwargs.append(f"params={json.dumps(step['params'], ensure_ascii=False)}")
            joined = (", " + ", ".join(kwargs)) if kwargs else ""
            lines.append(
                f'    resp = httpx.request("{method}", {json.dumps(url, ensure_ascii=False)}{joined}, timeout=30)'
            )
        for assertion in case.assertions or []:
            lines.extend(_api_assertion_lines(assertion))
        if not case.assertions:
            lines.append("    assert resp is not None")
        lines.append("")
    return "\n".join(lines)


def _api_assertion_lines(assertion: dict) -> list[str]:
    a_type = assertion.get("type")
    if a_type == "status_equals":
        return [f"    assert resp.status_code == {json.dumps(assertion.get('expected'))}"]
    if a_type == "json_field":
        return [
            f"    assert _json_path(resp.json(), {json.dumps(assertion.get('path', ''))}) "
            f"== {json.dumps(assertion.get('expected'), ensure_ascii=False)}"
        ]
    if a_type == "json_contains":
        return [
            f"    assert {json.dumps(str(assertion.get('expected')), ensure_ascii=False)} "
            f"in str(_json_path(resp.json(), {json.dumps(assertion.get('path', ''))}))"
        ]
    if a_type == "json_path_exists":
        return [
            f"    assert _json_path(resp.json(), {json.dumps(assertion.get('path', ''))}) is not None"
        ]
    if a_type == "json_schema":
        schema = json.dumps(assertion.get("schema") or {}, ensure_ascii=False)
        return [f"    jsonschema.validate(resp.json(), {schema})"]
    return [f"    # skip unsupported assertion: {a_type}"]


def render_ui_tests(cases: list) -> str:
    lines = [
        '"""自动生成的 UI 测试（Playwright sync）。"""',
        "from playwright.sync_api import sync_playwright",
        "",
    ]
    for idx, case in enumerate(cases, 1):
        lines.append(f"def {_func_name(idx, case.title)}():")
        lines.append(f'    """{case.title}"""')
        lines.append("    with sync_playwright() as p:")
        lines.append("        browser = p.chromium.launch(headless=True)")
        lines.append("        page = browser.new_page()")
        for step in case.steps or []:
            lines.extend(_ui_step_lines(step, case))
        for assertion in case.assertions or []:
            lines.extend(_ui_assertion_lines(assertion))
        lines.append("        browser.close()")
        lines.append("")
    return "\n".join(lines)


def _ui_step_lines(step: dict, case) -> list[str]:
    action = (step.get("action") or "").lower()
    selector = json.dumps(step.get("selector", ""), ensure_ascii=False)
    value = json.dumps(step.get("value", ""), ensure_ascii=False)
    if action in ("goto", "navigate"):
        url = step.get("value") or case.target_url
        return [f"        page.goto({json.dumps(url, ensure_ascii=False)})"]
    if action == "fill":
        return [f"        page.fill({selector}, {value})"]
    if action == "click":
        return [f"        page.click({selector})"]
    if action in ("select", "select_option"):
        return [f"        page.select_option({selector}, {value})"]
    if action == "check":
        return [f"        page.check({selector})"]
    if action == "hover":
        return [f"        page.hover({selector})"]
    if action == "press":
        return [f"        page.press({selector}, {value or json.dumps('Enter')})"]
    if action in ("wait_for", "waitfor"):
        return [f"        page.wait_for_selector({selector})"]
    if action == "wait":
        return [f"        page.wait_for_timeout({int(float(step.get('value') or 500))})"]
    return [f"        # skip unsupported action: {action}"]


def _ui_assertion_lines(assertion: dict) -> list[str]:
    a_type = assertion.get("type")
    selector = assertion.get("selector", "")
    expected = assertion.get("expected", "")
    if a_type == "text_contains":
        return [
            f"        assert {json.dumps(str(expected), ensure_ascii=False)} "
            f"in page.inner_text({json.dumps(selector, ensure_ascii=False)})"
        ]
    if a_type == "text_equals":
        return [
            f"        assert page.inner_text({json.dumps(selector, ensure_ascii=False)}) "
            f"== {json.dumps(str(expected), ensure_ascii=False)}"
        ]
    if a_type == "visible":
        return [f"        assert page.is_visible({json.dumps(selector, ensure_ascii=False)})"]
    return [f"        # skip unsupported assertion: {a_type}"]


_README = """# 自动生成测试工程

- `test_ui_generated.py`：UI 用例（Playwright）
- `test_api_generated.py`：接口用例（httpx）
- `conftest.py`：公共工具

## 运行

```bash
pip install -r requirements.txt
playwright install chromium
pytest -q
```
"""

_REQUIREMENTS = "pytest>=8.0\nhttpx>=0.27\nplaywright>=1.47\njsonschema>=4.0\n"


def build_pytest_zip(batch, cases: list, path: Path) -> Path:
    ui_cases = [c for c in cases if c.test_type == "ui"]
    api_cases = [c for c in cases if c.test_type == "api"]
    manifest = {
        "batch_id": batch.pk,
        "project": batch.project.key if batch.project_id else "",
        "ui_cases": [c.pk for c in ui_cases],
        "api_cases": [c.pk for c in api_cases],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("conftest.py", _CONFTEST)
        zf.writestr("test_ui_generated.py", render_ui_tests(ui_cases))
        zf.writestr("test_api_generated.py", render_api_tests(api_cases))
        zf.writestr("requirements.txt", _REQUIREMENTS)
        zf.writestr("README.md", _README)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return path


def build_json(batch, cases: list, path: Path) -> Path:
    payload = {
        "batch": {
            "id": batch.pk,
            "project": batch.project.key if batch.project_id else "",
            "doc_id": batch.doc_id,
            "status": batch.status,
            "total": batch.total,
            "generated": batch.generated,
            "executed": batch.executed,
            "healed": batch.healed,
        },
        "cases": [_case_dict(c) for c in cases],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ============================================================
# 入口
# ============================================================
def export_batch(batch_id: int, fmt: str):
    from apps.core.models import ExportJob, TestGenerationBatch
    from apps.testcases.models import TestCase

    batch = TestGenerationBatch.objects.select_related("project").get(pk=batch_id)
    job = ExportJob.objects.create(
        project=batch.project, batch=batch, format=fmt, status=ExportJob.Status.PENDING
    )
    try:
        cases = list(TestCase.objects.filter(id__in=batch.case_ids or []))
        filename = f"batch_{batch.pk}_{fmt}_{int(time.time())}.{_EXT[fmt]}"
        path = exports_dir() / filename

        if fmt == "xlsx":
            manual = [c for c in cases if c.kind == "manual"] or cases
            build_xlsx(manual, path)
        elif fmt == "pytest":
            build_pytest_zip(batch, [c for c in cases if c.kind == "automated"], path)
        elif fmt == "json":
            build_json(batch, cases, path)
        else:
            raise ValueError(f"unsupported format: {fmt}")

        job.file = str(path)
        job.status = ExportJob.Status.DONE
    except Exception as exc:  # noqa: BLE001
        job.status = ExportJob.Status.FAILED
        job.error = f"{type(exc).__name__}: {exc}"
    job.save()
    return job
