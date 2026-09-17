"""
文档解析服务：读取 RequirementDoc 文件 → 解析场景 → 写回 parsed_scenarios。
"""
from pathlib import Path

from apps.core.models import RequirementDoc, Scenario
from apps.core.parsers import get_parser


def _read_text(doc: RequirementDoc) -> str:
    doc.file.open("rb")
    try:
        raw = doc.file.read()
    finally:
        doc.file.close()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw or ""


def _guess_file_type(doc: RequirementDoc) -> str:
    if doc.file_type:
        return doc.file_type
    suffix = Path(doc.file.name or "").suffix
    return suffix.lstrip(".")


def parse_doc(doc_id: int) -> RequirementDoc:
    """解析需求文档，写回结构化场景与状态。"""
    doc = RequirementDoc.objects.get(pk=doc_id)
    doc.status = RequirementDoc.Status.PARSING
    doc.error_message = ""
    doc.save(update_fields=["status", "error_message", "updated_at"])

    try:
        text = _read_text(doc)
        parser = get_parser(_guess_file_type(doc), text)
        scenarios = parser.parse(text)
        doc.parsed_scenarios = scenarios
        _save_scenarios(doc, scenarios)
        doc.status = RequirementDoc.Status.PARSED
        doc.error_message = ""
    except Exception as exc:  # noqa: BLE001 - 解析失败写入状态，不抛出
        doc.status = RequirementDoc.Status.FAILED
        doc.error_message = f"{type(exc).__name__}: {exc}"

    doc.save(
        update_fields=[
            "parsed_scenarios", "status", "error_message", "updated_at"
        ]
    )
    return doc


def _save_scenarios(doc: RequirementDoc, scenarios: list[dict]) -> int:
    """用解析结果重建 Scenario 行（幂等：先删后建）。"""
    Scenario.objects.filter(doc_id=doc.pk).delete()
    rows = [
        Scenario(
            doc_id=doc.pk,
            project_id=doc.project_id,
            story_key=scenario.get("story_key", ""),
            epic=scenario.get("epic", ""),
            sprint=scenario.get("sprint", ""),
            module=scenario.get("module", ""),
            title=scenario.get("title", "") or "未命名场景",
            test_types=list(scenario.get("test_types") or []),
            priority=scenario.get("priority", "P1"),
            story_points=scenario.get("story_points"),
            role=scenario.get("role", ""),
            goal=scenario.get("goal", ""),
            benefit=scenario.get("benefit", ""),
            business_rules=list(scenario.get("business_rules") or []),
            test_data=dict(scenario.get("test_data") or {}),
            acceptance=list(scenario.get("acceptance") or []),
            definition_of_done=list(scenario.get("definition_of_done") or []),
            automation=dict(scenario.get("automation") or {}),
            api_ref=scenario.get("api_ref", ""),
            api_spec=dict(scenario.get("api") or {}),
            env=dict(scenario.get("env") or {}),
            tags=list(scenario.get("tags") or []),
            raw_text=scenario.get("raw_text", ""),
            source=scenario.get("source", "story"),
        )
        for scenario in scenarios
    ]
    if rows:
        Scenario.objects.bulk_create(rows)
    return len(rows)
