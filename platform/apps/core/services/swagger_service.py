"""
Swagger/OpenAPI 导入服务（Phase J Step 3）。

拉取项目公开 swagger_url → 解析 endpoints → 生成接口场景 → 落库 Scenario(source=swagger)。
best-effort：拉取/解析失败仅告警，不阻断主流程。
"""
import logging

from apps.core.models import RequirementDoc, Scenario
from apps.core.parsers.openapi_parser import (
    base_url_from_spec,
    endpoints_to_scenarios,
    fetch_spec,
    is_openapi,
    parse_endpoints,
)

logger = logging.getLogger(__name__)


def import_swagger_for_doc(
    doc: RequirementDoc, url: str = "", base_url: str = ""
) -> int:
    """拉取 spec 并写入 Scenario，返回新增数量（失败返回 0）。"""
    swagger_url = url or (doc.project.swagger_url if doc.project_id else "")
    if not swagger_url:
        return 0
    try:
        spec = fetch_spec(swagger_url)
        if not is_openapi(spec):
            logger.warning("swagger url is not an OpenAPI spec: %s", swagger_url)
            return 0
        resolved_base = base_url or (doc.project.api_base_url if doc.project_id else "") or base_url_from_spec(spec)
        scenarios = endpoints_to_scenarios(parse_endpoints(spec), resolved_base)
    except Exception as exc:  # noqa: BLE001 - 拉取失败不阻断
        logger.warning("import swagger failed (%s): %s", swagger_url, exc)
        return 0

    Scenario.objects.filter(doc_id=doc.pk, source="swagger").delete()
    rows = [_to_scenario(doc, scenario) for scenario in scenarios]
    if rows:
        Scenario.objects.bulk_create(rows)
    return len(rows)


def _to_scenario(doc: RequirementDoc, scenario: dict) -> Scenario:
    return Scenario(
        doc_id=doc.pk,
        project_id=doc.project_id,
        story_key=scenario.get("story_key", ""),
        module=scenario.get("module", ""),
        title=scenario.get("title", "") or "未命名接口场景",
        test_types=list(scenario.get("test_types") or []),
        priority=scenario.get("priority", "P1"),
        business_rules=[],
        test_data={},
        acceptance=[],
        automation=dict(scenario.get("automation") or {}),
        api_ref=scenario.get("api_ref", ""),
        api_spec=dict(scenario.get("api") or {}),
        env=dict(scenario.get("env") or {}),
        tags=list(scenario.get("tags") or []),
        raw_text=scenario.get("raw_text", ""),
        source="swagger",
    )
