"""
执行报告生成（Phase E）

跑完一个 TestRun 后输出：
- JSON: media/reports/run_{id}.json
- HTML: media/reports/run_{id}.html （用例名 / 步骤 / 断言 / 结果 / 耗时）
"""
import html
import json
from pathlib import Path

from django.conf import settings


def _reports_dir() -> Path:
    out_dir = Path(settings.MEDIA_ROOT) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def build_report_payload(run) -> dict:
    """把一个 TestRun 组装成可序列化的报告结构。"""
    cases: dict[int, dict] = {}
    for sr in run.step_results.select_related("testcase").all():
        entry = cases.setdefault(
            sr.testcase_id,
            {
                "case_id": sr.testcase_id,
                "title": sr.testcase.title,
                "priority": sr.testcase.priority,
                "steps": [],
            },
        )
        entry["steps"].append(
            {
                "index": sr.step_index,
                "phase": sr.phase,
                "action": sr.action,
                "selector": sr.selector,
                "value": sr.value,
                "expected": sr.expected,
                "actual": sr.actual,
                "status": sr.status,
                "error": sr.error,
                "screenshot_path": sr.screenshot_path,
                "duration_ms": sr.duration_ms,
            }
        )

    for entry in cases.values():
        statuses = {s["status"] for s in entry["steps"]}
        if {"fail", "error"} & statuses:
            entry["status"] = "fail"
        elif statuses <= {"skip"}:
            entry["status"] = "skipped"
        else:
            entry["status"] = "pass"
        entry["duration_ms"] = sum(s["duration_ms"] for s in entry["steps"])

    return {
        "run": {
            "id": run.pk,
            "project_id": run.project_id,
            "goal": run.goal,
            "source": run.source,
            "status": run.status,
            "total_cases": run.total_cases,
            "passed_cases": run.passed_cases,
            "failed_cases": run.failed_cases,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        },
        "cases": list(cases.values()),
    }


def write_report(run) -> dict:
    """写出 JSON + HTML 报告，返回两个路径。"""
    payload = build_report_payload(run)
    out_dir = _reports_dir()

    json_path = out_dir / f"run_{run.pk}.json"
    html_path = out_dir / f"run_{run.pk}.html"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    html_path.write_text(_render_html(payload), encoding="utf-8")

    return {"json": str(json_path), "html": str(html_path)}


_STATUS_STYLE = {
    "pass": ("#e6f4ea", "#1e7e34"),
    "fail": ("#fdecea", "#c62828"),
    "error": ("#fff3e0", "#e65100"),
    "skip": ("#f0f0f0", "#616161"),
    "skipped": ("#f0f0f0", "#616161"),
    "running": ("#e3f2fd", "#1565c0"),
}


def _badge(status: str) -> str:
    bg, fg = _STATUS_STYLE.get(status, ("#f0f0f0", "#333"))
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;'
        f'border-radius:10px;font-size:12px;">{html.escape(status)}</span>'
    )


def _render_html(payload: dict) -> str:
    run = payload["run"]
    rows = []
    for case in payload["cases"]:
        rows.append(
            f'<tr><td colspan="6" style="background:#fafafa;">'
            f'<b>#{case["case_id"]} [{html.escape(case["priority"])}] '
            f'{html.escape(case["title"])}</b> &nbsp; {_badge(case["status"])} '
            f'&nbsp; {case["duration_ms"]} ms</td></tr>'
        )
        for s in case["steps"]:
            rows.append(
                "<tr>"
                f'<td>{html.escape(str(s["phase"]))}{s["index"]}</td>'
                f'<td>{html.escape(s["action"])}</td>'
                f'<td><code>{html.escape(s["selector"])}</code></td>'
                f'<td>{html.escape(s["expected"])}</td>'
                f'<td>{html.escape(s["actual"])}</td>'
                f'<td>{_badge(s["status"])} <small>{s["duration_ms"]}ms</small></td>'
                "</tr>"
            )
            if s.get("error"):
                rows.append(
                    f'<tr><td></td><td colspan="5" style="color:#c62828;">'
                    f'{html.escape(s["error"])}</td></tr>'
                )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>TestRun #{run["id"]} Report</title>
  <style>
    body {{ font-family: -apple-system, "PingFang SC", sans-serif; margin: 24px; color: #222; }}
    h1 {{ font-size: 20px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border: 1px solid #e0e0e0; padding: 6px 10px; font-size: 13px; text-align: left; }}
    th {{ background: #f5f5f5; }}
    code {{ background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }}
    .meta {{ color: #555; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>执行报告 · TestRun #{run["id"]} {_badge(run["status"])}</h1>
  <p class="meta">
    project: {html.escape(run["project_id"])} &nbsp;|&nbsp;
    goal: {html.escape(run["goal"])} &nbsp;|&nbsp;
    source: {html.escape(run["source"])} &nbsp;|&nbsp;
    cases: {run["passed_cases"]}/{run["total_cases"]} passed &nbsp;|&nbsp;
    started: {html.escape(str(run["started_at"]))} &nbsp;|&nbsp;
    finished: {html.escape(str(run["finished_at"]))}
  </p>
  <table>
    <thead>
      <tr><th>Step</th><th>Action</th><th>Selector</th><th>Expected</th><th>Actual</th><th>Result</th></tr>
    </thead>
    <tbody>
      {''.join(rows) or '<tr><td colspan="6">no steps</td></tr>'}
    </tbody>
  </table>
</body>
</html>
"""
