"""
RAG 服务：Qdrant 向量存储 + Reranker 重排

存储内容：
- 需求文档 (PRD)
- 接口规范 (OpenAPI/Swagger)
- 历史测试用例
- 历史缺陷/ Bug 记录
- 业务规则

检索策略：混合检索 (BM25 关键词 + 向量语义) + Reranker 重排
"""
import os
import hashlib
from typing import Optional
from pydantic import BaseModel


class Document(BaseModel):
    """入库文档"""
    content: str
    source: str           # 文件路径 / URL / 用例ID
    doc_type: str         # "prd" / "api_spec" / "testcase" / "bug" / "rule"
    project_id: str = ""
    metadata: dict = {}


class RetrievalResult(BaseModel):
    content: str
    score: float
    source: str
    doc_type: str
    metadata: dict = {}


# ============================================================
# 嵌入 & Rerank (兼容 OpenAI API 的本地/远程模型)
# ============================================================
async def embed(texts: list[str]) -> list[list[float]]:
    """
    生成嵌入向量。
    推荐: BAAI/bge-large-zh-v1.5 (中文最优)
    可切换: text-embedding-3-large / 本地 Ollama
    """
    import httpx
    base_url = os.getenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1")
    api_key = os.getenv("EMBEDDING_API_KEY", "EMPTY")
    model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/embeddings",
            json={"model": model, "input": texts},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        data = resp.json()
    return [item["embedding"] for item in data["data"]]


async def rerank(query: str, documents: list[str], top_k: int = 5) -> list[int]:
    """
    Reranker 重排（BGE-Reranker-v2-m3）
    返回重排后的索引列表
    """
    import httpx
    base_url = os.getenv("RERANK_BASE_URL", "http://localhost:8001")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/rerank",
                json={"query": query, "documents": documents, "top_k": top_k},
                timeout=30,
            )
            data = resp.json()
        return [item["index"] for item in data["results"]]
    except Exception:
        # Reranker 不可用时退化为原始顺序
        return list(range(min(top_k, len(documents))))


# ============================================================
# Qdrant 操作
# ============================================================
def _get_qdrant():
    from qdrant_client import AsyncQdrantClient
    return AsyncQdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        api_key=os.getenv("QDRANT_API_KEY"),
    )


COLLECTION_NAME = "test_knowledge"


async def ensure_collection(vector_size: int = 1024):
    """确保 collection 存在（按 embedding 维度调整）"""
    client = _get_qdrant()
    collections = await client.get_collections()
    if COLLECTION_NAME not in [c.name for c in collections.collections]:
        from qdrant_client.models import VectorParams, Distance
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=vector_size, distance=Distance.COSINE
            ),
        )


async def ingest_document(doc: Document):
    """文档入库：分块 → 嵌入 → 写入 Qdrant"""
    await ensure_collection()

    # 简单分块（生产建议用语义分块）
    chunks = _split_text(doc.content, chunk_size=500, overlap=50)

    vectors = await embed(chunks)
    client = _get_qdrant()

    from qdrant_client.models import PointStruct
    points = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        point_id = hashlib.md5(
            f"{doc.source}:{i}".encode()
        ).hexdigest()
        points.append(PointStruct(
            id=point_id,
            vector=vector,
            payload={
                "content": chunk,
                "source": doc.source,
                "doc_type": doc.doc_type,
                "project_id": doc.project_id,
                "metadata": doc.metadata,
            },
        ))

    await client.upsert(collection_name=COLLECTION_NAME, points=points)


async def retrieve(
    query: str,
    project_id: str = "",
    top_k: int = 10,
    doc_types: Optional[list[str]] = None,
) -> list[dict]:
    """
    混合检索 + Reranker 重排

    1. 向量检索 (top_k * 3 候选)
    2. Reranker 精排 → top_k
    """
    await ensure_collection()
    client = _get_qdrant()

    # 构建过滤条件
    filters = {}
    if project_id:
        filters["project_id"] = project_id
    if doc_types:
        filters["doc_type"] = {"$in": doc_types}

    # 1. 向量检索
    query_vector = (await embed([query]))[0]
    search_result = await client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k * 3,
        query_filter=filters if filters else None,
    )

    candidates = [hit.payload for hit in search_result]
    if not candidates:
        return []

    # 2. Reranker 重排
    reranked_idx = await rerank(
        query,
        [c["content"] for c in candidates],
        top_k=min(top_k, len(candidates)),
    )

    results = []
    for idx in reranked_idx:
        c = candidates[idx]
        results.append({
            "content": c["content"],
            "score": c.get("score", 0.0),
            "source": c["source"],
            "doc_type": c["doc_type"],
            "metadata": c.get("metadata", {}),
        })
    return results


# ============================================================
# 文本分块
# ============================================================
def _split_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[str]:
    """按字符数滑动窗口分块"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return [c for c in chunks if c.strip()]
