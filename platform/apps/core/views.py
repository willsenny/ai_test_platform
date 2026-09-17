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
import threading
from pathlib import Path

from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView
from rest_framework import viewsets

from .models import Project, RequirementDoc, TestGenerationBatch
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


class BatchDetailView(DetailView):
    template_name = "core/batch_detail.html"
    context_object_name = "batch"
    queryset = TestGenerationBatch.objects.select_related("project", "doc", "run")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        batch = self.object
        from apps.testcases.models import TestCase

        context["cases"] = TestCase.objects.filter(id__in=batch.case_ids or [])
        if batch.run_id:
            context["failed_steps"] = batch.run.step_results.filter(
                status__in=["fail", "error"]
            ).select_related("testcase")
        return context


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
