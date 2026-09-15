"""
失败分析器（Phase F · 规则驱动）

从 TestStepResult 提取失败特征，按错误信息匹配失败类型：
- element_not_found → suspect_selector
- text_mismatch     → suspect_assertion
- timeout           → suspect_timing
- navigation_failed → suspect_url
"""
from dataclasses import asdict, dataclass, field

SUSPECT_BY_TYPE = {
    "element_not_found": "suspect_selector",
    "text_mismatch": "suspect_assertion",
    "timeout": "suspect_timing",
    "navigation_failed": "suspect_url",
    "unknown": "suspect_unknown",
}

_SELECTOR_MARKERS = (
    "waiting for locator",
    "no element",
    "strict mode violation",
    "not found",
    "did not find",
    "no node found",
    "element is not attached",
)
# 元素已找到但不可操作 → 时序问题（优先于 selector 判定）
_ACTION_TIMING_MARKERS = (
    "enabled and stable",
    "element is not visible",
    "is not enabled",
    "not stable",
    "not editable",
    "intercepts pointer events",
)
_TIMING_GENERIC = ("timeout", "timed out")
_NAV_MARKERS = ("net::", "err_", "ns_error", "navigation", "page.goto")


@dataclass
class FailureFeature:
    step_id: int
    case_id: int
    run_id: int
    phase: str
    action: str
    selector: str
    value: str
    expected: str
    actual: str
    error: str
    failure_type: str
    suspect: str
    confidence: float
    # Phase G：从 step_results 检索到的历史同类失败
    similar_failures: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def classify(phase: str, expected: str, actual: str, error: str) -> tuple[str, float]:
    """返回 (failure_type, confidence)。"""
    e = (error or "").lower()

    if any(m in e for m in _ACTION_TIMING_MARKERS):
        return "timeout", 0.85
    if any(m in e for m in _SELECTOR_MARKERS):
        return "element_not_found", 0.9
    if any(m in e for m in _NAV_MARKERS):
        return "navigation_failed", 0.8
    if any(m in e for m in _TIMING_GENERIC):
        return "timeout", 0.8

    if phase == "assert":
        if expected != actual:
            return "text_mismatch", 0.85
        return "text_mismatch", 0.5

    if error:
        return "element_not_found", 0.4
    return "unknown", 0.2


def analyze_step(step) -> FailureFeature:
    failure_type, confidence = classify(
        phase=step.phase,
        expected=step.expected or "",
        actual=step.actual or "",
        error=step.error or "",
    )
    return FailureFeature(
        step_id=step.pk,
        case_id=step.testcase_id,
        run_id=step.run_id,
        phase=step.phase,
        action=step.action or "",
        selector=step.selector or "",
        value=step.value or "",
        expected=step.expected or "",
        actual=step.actual or "",
        error=step.error or "",
        failure_type=failure_type,
        suspect=SUSPECT_BY_TYPE.get(failure_type, "suspect_unknown"),
        confidence=confidence,
    )


def analyze_case(case_id: int, step_ids: list[int] | None = None) -> list[FailureFeature]:
    """分析某用例的失败步骤（默认只看最近一次 TestRun 的失败）。"""
    from apps.executor.models import TestStepResult

    qs = TestStepResult.objects.filter(testcase_id=case_id)
    if step_ids:
        qs = qs.filter(pk__in=step_ids)
    else:
        latest_run = (
            TestStepResult.objects.filter(testcase_id=case_id)
            .order_by("-run_id")
            .values_list("run_id", flat=True)
            .first()
        )
        if latest_run is not None:
            qs = qs.filter(run_id=latest_run)

    qs = qs.filter(status__in=["fail", "error"]).order_by("step_index")
    features = [analyze_step(s) for s in qs]

    # Phase G：为每个失败特征检索历史同类失败（Qdrant 不可用时返回空，不阻断）
    try:
        from apps.rag.retriever import retrieve_similar_failures

        for feature in features:
            feature.similar_failures = retrieve_similar_failures(
                feature.selector, feature.error, top_k=3
            )
    except Exception:  # noqa: BLE001
        pass

    return features
