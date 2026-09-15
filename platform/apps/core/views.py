"""
项目管理 API

GET/POST      /api/v1/projects/
GET/PUT/PATCH/DELETE /api/v1/projects/{id}/
"""
from rest_framework import viewsets

from .models import Project
from .serializers import ProjectSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
