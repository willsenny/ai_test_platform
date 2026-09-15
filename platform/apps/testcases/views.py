"""
用例库 API

GET/POST             /api/v1/testcases/
GET/PUT/PATCH/DELETE /api/v1/testcases/{id}/
支持 ?project_id=xxx 过滤
"""
from rest_framework import viewsets

from .models import TestCase
from .serializers import TestCaseSerializer


class TestCaseViewSet(viewsets.ModelViewSet):
    serializer_class = TestCaseSerializer

    def get_queryset(self):
        queryset = TestCase.objects.all()
        project_id = self.request.query_params.get("project_id")
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset
