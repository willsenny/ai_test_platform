"""
批量生成服务：需求文档 parsed_scenarios → 用例 → 执行 → 自愈。

链路（Phase I）：
    generate_from_doc(doc_id)
      → 逐场景调 build_generation_graph（planner→generator→reporter）
      → execute_cases(auto_heal=True) 自动执行 + 自愈
      → 回写 TestGenerationBatch 计数
"""
import logging

from asgiref.sync import sync_to_async

from apps.core.models import Project, RequirementDoc, TestGenerationBatch

logger = logging.getLogger(__name__)


def build_scenario_goal(scenario: dict) -> str:
    """把场景结构压成生成用的目标文本。"""
    parts = [scenario.get("title", "")]
    description = scenario.get("description", "")
    if description:
        parts.append(description)
    acceptance = scenario.get("acceptance_criteria") or []
    if acceptance:
        parts.append("验收标准：" + "；".join(acceptance))
    return "\n".join(p for p in parts if p)


def scenario_to_dict(scenario) -> dict:
    """core.Scenario → 生成用 dict（含 scenario_id 追溯）。"""
    acceptance = list(scenario.acceptance or [])
    criteria = [
        (item.get("name", "") + "：" + "；".join(item.get("then", []))).strip("：")
        for item in acceptance
        if item.get("name") or item.get("then")
    ]
    description_parts = [p for p in (scenario.goal, scenario.benefit) if p]
    if scenario.business_rules:
        description_parts.append("业务规则：" + "；".join(scenario.business_rules))
    test_types = list(scenario.test_types or [])
    primary = "ui" if "ui" in test_types else ("api" if "api" in test_types else "functional")
    return {
        "scenario_id": scenario.pk,
        "title": scenario.title,
        "story_key": scenario.story_key,
        "epic": scenario.epic,
        "sprint": scenario.sprint,
        "module": scenario.module,
        "test_types": test_types,
        "type": primary,
        "priority": scenario.priority,
        "story_points": scenario.story_points,
        "role": scenario.role,
        "goal": scenario.goal,
        "benefit": scenario.benefit,
        "business_rules": list(scenario.business_rules or []),
        "test_data": dict(scenario.test_data or {}),
        "acceptance": acceptance,
        "definition_of_done": list(scenario.definition_of_done or []),
        "automation": dict(scenario.automation or {}),
        "api_ref": scenario.api_ref,
        "env": dict(scenario.env or {}),
        "tags": list(scenario.tags or []),
        "raw_text": scenario.raw_text,
        "description": "\n".join(description_parts),
        "acceptance_criteria": criteria,
    }


# ------------------------------------------------------------
# DB helpers（同步，供 sync_to_async 包装）
# ------------------------------------------------------------
def _load_doc(doc_id: int) -> RequirementDoc:
    return RequirementDoc.objects.select_related("project").get(pk=doc_id)


def _load_scenarios(doc_id: int) -> list:
    from apps.core.models import Scenario

    return list(Scenario.objects.filter(doc_id=doc_id).order_by("id"))


def _automated_case_ids(case_ids: list[int]) -> list[int]:
    """手动用例不参与自动执行。"""
    from apps.testcases.models import TestCase

    return list(
        TestCase.objects.filter(
            id__in=case_ids, kind=TestCase.Kind.AUTOMATED
        ).values_list("id", flat=True)
    )


def _load_project(project_id) -> Project | None:
    if not project_id:
        return None
    if isinstance(project_id, int):
        return Project.objects.filter(pk=project_id).first()
    return Project.objects.filter(key=str(project_id)).first()


def _create_batch(project_pk: int, doc_pk: int, total: int) -> TestGenerationBatch:
    return TestGenerationBatch.objects.create(
        project_id=project_pk,
        doc_id=doc_pk,
        total=total,
        status=TestGenerationBatch.Status.GENERATING,
    )


def _update_batch(batch_id: int, **fields) -> None:
    TestGenerationBatch.objects.filter(pk=batch_id).update(**fields)


def _mark_doc(doc_id: int, status: str, error_message: str = "") -> None:
    RequirementDoc.objects.filter(pk=doc_id).update(
        status=status, error_message=error_message
    )


# ------------------------------------------------------------
# 主入口
# ------------------------------------------------------------
async def generate_from_doc(
    doc_id: int,
    *,
    project_id=None,
    api_base_url: str = "",
    ui_target_url: str = "",
    case_count: int = 3,
    execute: bool = True,
    self_heal: bool = True,
    source: str = "doc:batch",
) -> TestGenerationBatch:
    """解析结果 → 批量生成 → 自动执行 → 自动自愈，并回写批次计数。"""
    from apps.agent.graph import get_generation_graph

    doc = await sync_to_async(_load_doc)(doc_id)
    project = doc.project or await sync_to_async(_load_project)(project_id)
    if project is None:
        raise ValueError(
            f"RequirementDoc #{doc_id} has no project and no project_id given"
        )

    scenario_rows = await sync_to_async(_load_scenarios)(doc.pk)
    if scenario_rows:
        scenarios = [scenario_to_dict(s) for s in scenario_rows]
    else:
        scenarios = list(doc.parsed_scenarios or [])
    batch = await sync_to_async(_create_batch)(project.pk, doc.pk, len(scenarios))
    await sync_to_async(_mark_doc)(
        doc.pk, RequirementDoc.Status.GENERATING, ""
    )

    graph = get_generation_graph()
    case_ids: list[int] = []
    errors: list[str] = []

    for scenario in scenarios:
        state = {
            "requirement": build_scenario_goal(scenario),
            "project_id": project.key,
            "project_ref_pk": project.pk,
            "case_type": scenario.get("type", "ui"),
            "scenario": scenario,
            "case_count": case_count,
            "api_base_url": api_base_url or project.api_base_url,
            "ui_target_url": ui_target_url or project.base_url,
            "source": source,
            "test_cases": [],
            "retrieved_cases": [],
        }
        try:
            result = await graph.ainvoke(state)
            case_ids.extend(result.get("saved_ids", []))
        except Exception as exc:  # noqa: BLE001 - 单场景失败不阻断整批
            errors.append(f"{scenario.get('title', '?')}: {type(exc).__name__}: {exc}")

    await sync_to_async(_update_batch)(
        batch.pk,
        generated=len(case_ids),
        case_ids=case_ids,
        status=TestGenerationBatch.Status.EXECUTING,
    )

    executed = 0
    healed = 0
    automated_ids = await sync_to_async(_automated_case_ids)(case_ids)
    if execute and automated_ids:
        from apps.executor.executor import execute_cases

        try:
            result = await execute_cases(
                automated_ids,
                goal=doc.title or f"doc#{doc.pk}",
                source=source,
                project_id=project.key,
                auto_heal=self_heal,
            )
            executed = result.get("total", 0)
            healed = result.get("healed", 0)
            await sync_to_async(_update_batch)(
                batch.pk,
                run_id=result.get("run_id"),
                executed=executed,
                healed=healed,
                status=TestGenerationBatch.Status.DONE,
                error_message="; ".join(errors),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"execute: {type(exc).__name__}: {exc}")
            await sync_to_async(_update_batch)(
                batch.pk,
                executed=executed,
                healed=healed,
                status=TestGenerationBatch.Status.FAILED,
                error_message="; ".join(errors),
            )
    else:
        await sync_to_async(_update_batch)(
            batch.pk,
            status=TestGenerationBatch.Status.DONE,
            error_message="; ".join(errors),
        )

    if case_ids:
        await sync_to_async(_mark_doc)(
            doc.pk, RequirementDoc.Status.DONE, "; ".join(errors)
        )
    else:
        await sync_to_async(_mark_doc)(
            doc.pk,
            RequirementDoc.Status.FAILED,
            "; ".join(errors) or "no test cases generated",
        )

    return await sync_to_async(
        lambda: TestGenerationBatch.objects.get(pk=batch.pk)
    )()
