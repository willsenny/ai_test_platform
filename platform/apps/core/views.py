"""
项目管理 API + Phase I Web 最小入口。

API:
    GET/POST             /api/v1/projects/
    GET/PUT/PATCH/DELETE /api/v1/projects/{id}/

Web:
    GET  /                    项目列表
    GET  /docs/upload/        上传需求文档
    GET  /batches/{id}/       批次进度
    GET  /batches/{id}/report/ 执行报告
"""
import asyncio
import json
import re
import threading
from pathlib import Path

from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView
from rest_framework import viewsets

from .models import Project, RequirementDoc, Scenario, TestGenerationBatch
from .serializers import ProjectSerializer
from .services.doc_service import parse_doc


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer


# ============================================================
# Web 视图
# ============================================================
def _start_generation(doc_id: int, project_id: str, api_base_url: str = "") -> None:
    """后台线程跑「生成 → 执行 → 自愈」，避免阻塞请求。"""
    def target():
        from django.db import close_old_connections

        close_old_connections()
        try:
            from .services.generation_service import generate_from_doc

            asyncio.run(
                generate_from_doc(
                    doc_id, project_id=project_id, api_base_url=api_base_url
                )
            )
        except Exception:  # noqa: BLE001 - 后台任务失败不影响请求
            import logging

            logging.getLogger(__name__).exception("generation pipeline failed")
        finally:
            close_old_connections()

    threading.Thread(target=target, daemon=True).start()


class ProjectListView(ListView):
    template_name = "core/projects.html"
    context_object_name = "projects"

    def get_queryset(self):
        return Project.objects.prefetch_related("requirements", "generation_batches")


class DocUploadView(View):
    template_name = "core/upload.html"

    def get(self, request):
        return render(request, self.template_name, {"projects": Project.objects.all()})

    def post(self, request):
        project_id = request.POST.get("project_id")
        upload = request.FILES.get("file")
        project = Project.objects.filter(pk=project_id).first()
        if project is None or upload is None:
            return render(
                request,
                self.template_name,
                {
                    "projects": Project.objects.all(),
                    "error": "请选择项目并上传 Markdown 需求文档",
                },
            )

        file_type = Path(upload.name).suffix.lstrip(".") or "md"
        doc = RequirementDoc.objects.create(
            project=project,
            title=Path(upload.name).stem,
            file=upload,
            file_type=file_type,
        )
        parse_doc(doc.pk)
        _start_generation(doc.pk, project.key, project.api_base_url)

        batches = TestGenerationBatch.objects.filter(doc_id=doc.pk)
        if batches.exists():
            return redirect("web-batch-detail", pk=batches.first().pk)
        return redirect("web-projects")


def _start_rerun(batch_id: int) -> None:
    """后台线程重新执行批次中的自动化用例（含自愈）。"""
    def target():
        from django.db import close_old_connections

        close_old_connections()
        try:
            from apps.executor.executor import execute_cases
            from apps.testcases.models import TestCase

            batch = TestGenerationBatch.objects.select_related("project").get(pk=batch_id)
            case_ids = list(
                TestCase.objects.filter(
                    id__in=batch.case_ids or [], kind=TestCase.Kind.AUTOMATED
                ).values_list("id", flat=True)
            )
            if case_ids:
                result = asyncio.run(
                    execute_cases(
                        case_ids,
                        goal=batch.doc.title or f"batch#{batch.pk}",
                        source="web:rerun",
                        project_id=batch.project.key,
                        auto_heal=True,
                    )
                )
                TestGenerationBatch.objects.filter(pk=batch_id).update(
                    run_id=result.get("run_id"),
                    executed=result.get("total", 0),
                    healed=result.get("healed", 0),
                    status=TestGenerationBatch.Status.DONE,
                )
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("rerun failed")
        finally:
            close_old_connections()

    threading.Thread(target=target, daemon=True).start()


class DocDetailView(DetailView):
    template_name = "core/doc_detail.html"
    context_object_name = "doc"
    queryset = RequirementDoc.objects.select_related("project")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["scenarios"] = self.object.scenarios.all()
        context["batches"] = self.object.batches.all()
        return context


def _split_list(value: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,，、\s]+", value or "") if t.strip()]


def _split_lines(value: str) -> list[str]:
    return [line.strip(" -") for line in (value or "").splitlines() if line.strip()]


def _parse_json_dict(value: str) -> dict:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


class ScenarioEditView(View):
    """审核 / 编辑单个需求场景。"""

    template_name = "core/scenario_edit.html"

    def get(self, request, pk):
        scenario = get_object_or_404(Scenario, pk=pk)
        return render(
            request,
            self.template_name,
            {
                "scenario": scenario,
                "test_data_json": json.dumps(scenario.test_data or {}, ensure_ascii=False, indent=2),
            },
        )

    def post(self, request, pk):
        scenario = get_object_or_404(Scenario, pk=pk)
        scenario.title = request.POST.get("title", "").strip() or scenario.title
        scenario.priority = request.POST.get("priority") or scenario.priority
        scenario.module = request.POST.get("module", "")
        scenario.tags = _split_list(request.POST.get("tags", ""))
        scenario.business_rules = _split_lines(request.POST.get("business_rules", ""))
        scenario.test_data = _parse_json_dict(request.POST.get("test_data", "{}"))
        scenario.automation = {
            "manual": request.POST.get("auto_manual") == "on",
            "ui": request.POST.get("auto_ui") == "on",
            "api": request.POST.get("auto_api") == "on",
        }
        scenario.save()
        return redirect("web-doc-detail", pk=scenario.doc_id)


class BatchRunView(View):
    """触发批次重新执行（含自愈）。"""

    def post(self, request, pk):
        batch = get_object_or_404(TestGenerationBatch, pk=pk)
        _start_rerun(batch.pk)
        return redirect("web-batch-detail", pk=batch.pk)


class BatchDetailView(DetailView):
    template_name = "core/batch_detail.html"
    context_object_name = "batch"
    queryset = TestGenerationBatch.objects.select_related("project", "doc", "run")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        batch = self.object
        from apps.testcases.models import TestCase

        cases = TestCase.objects.filter(id__in=batch.case_ids or [])
        kind = self.request.GET.get("kind", "")
        if kind in ("manual", "automated"):
            cases = cases.filter(kind=kind)
        context["cases"] = cases
        context["kind"] = kind
        context["manual_total"] = TestCase.objects.filter(
            id__in=batch.case_ids or [], kind=TestCase.Kind.MANUAL
        ).count()
        context["automated_total"] = TestCase.objects.filter(
            id__in=batch.case_ids or [], kind=TestCase.Kind.AUTOMATED
        ).count()

        if batch.run_id:
            context["failed_steps"] = batch.run.step_results.filter(
                status__in=["fail", "error"]
            ).select_related("testcase")

        from apps.selfheal.models import SelfHealLog

        context["heal_logs"] = SelfHealLog.objects.all()[:10]
        return context


_EXPORT_CONTENT_TYPE = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pytest": "application/zip",
    "json": "application/json",
}


class BatchExportView(View):
    """导出批次：手动用例 xlsx / 自动化 pytest 工程 / JSON 存档。"""

    def get(self, request, pk, fmt):
        if fmt not in _EXPORT_CONTENT_TYPE:
            return HttpResponseNotFound("不支持的导出格式")
        batch = get_object_or_404(TestGenerationBatch, pk=pk)
        from .services.export_service import export_batch

        job = export_batch(batch.pk, fmt)
        if job.status != "done" or not job.file:
            return HttpResponseNotFound(f"导出失败: {job.error}")

        path = Path(job.file)
        response = HttpResponse(
            path.read_bytes(), content_type=_EXPORT_CONTENT_TYPE[fmt]
        )
        response["Content-Disposition"] = f'attachment; filename="{path.name}"'
        return response


class ReportView(View):
    """直接返回 TestRun 生成的 HTML 报告。"""

    def get(self, request, pk):
        batch = get_object_or_404(
            TestGenerationBatch.objects.select_related("run"), pk=pk
        )
        if batch.run_id and batch.run.report_html:
            path = Path(batch.run.report_html)
            if path.exists():
                return HttpResponse(
                    path.read_text(encoding="utf-8"), content_type="text/html"
                )
        return HttpResponseNotFound("报告尚未生成")
