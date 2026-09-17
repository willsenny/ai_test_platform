"""
文档解析服务：读取 RequirementDoc 文件 → 解析场景 → 写回 parsed_scenarios。
"""
from pathlib import Path

from apps.core.models import RequirementDoc
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
        parser = get_parser(_guess_file_type(doc))
        scenarios = parser.parse(text)
        doc.parsed_scenarios = scenarios
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
