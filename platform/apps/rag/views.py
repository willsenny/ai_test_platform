"""
RAG API 端点

POST /api/v1/rag/ingest    - 文档入库
POST /api/v1/rag/retrieve  - 检索
GET  /api/v1/rag/collections - 列出 collection
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .service import ingest_document, retrieve, Document


class IngestView(APIView):
    """
    POST /api/v1/rag/ingest

    Body:
        {
            "content": "...",
            "source": "prd/login.md",
            "doc_type": "prd",   # prd/api_spec/testcase/bug/rule
            "project_id": "proj_123",
            "metadata": {}
        }
    """

    async def post(self, request):
        doc = Document(
            content=request.data.get("content", ""),
            source=request.data.get("source", ""),
            doc_type=request.data.get("doc_type", "unknown"),
            project_id=request.data.get("project_id", ""),
            metadata=request.data.get("metadata", {}),
        )
        await ingest_document(doc)
        return Response({"status": "ingested", "source": doc.source})


class RetrieveView(APIView):
    """
    POST /api/v1/rag/retrieve

    Body:
        {
            "query": "用户登录 验证码",
            "project_id": "proj_123",
            "top_k": 10,
            "doc_types": ["prd", "api_spec"]  # 可选过滤
        }
    """

    async def post(self, request):
        results = await retrieve(
            query=request.data.get("query", ""),
            project_id=request.data.get("project_id", ""),
            top_k=int(request.data.get("top_k", 10)),
            doc_types=request.data.get("doc_types"),
        )
        return Response({"count": len(results), "results": results})
