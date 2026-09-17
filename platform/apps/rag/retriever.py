"""
向量检索（Phase G）

- 统一入口 retrieve(query, collection, top_k) -> [{id, payload, score}]
- 三个业务方法：
    retrieve_similar_cases(goal)        历史相似用例（testcases）
    retrieve_similar_failures(selector) 历史同类失败（step_results）
    retrieve_heal_experience(pattern)   历史成功修复经验（heal_logs）

Qdrant 就绪策略（无 Docker 的降级）：
- QDRANT_MODE=auto（默认）：先试 QDRANT_URL，不可达则回退到本地嵌入式
  Qdrant（qdrant-client local 持久化目录），API 与远端一致。
- remote / local / memory / off 可显式指定。
- 任何异常（未安装 qdrant-client、连不上、维度不符）都不阻断调用方，返回 []。
不做 reranker 精排，仅用 score 阈值过滤。
"""
from __future__ import annotations

import atexit
import logging
import os
import threading

logger = logging.getLogger(__name__)

COLLECTION_TESTCASES = "testcases"
COLLECTION_STEP_RESULTS = "step_results"
COLLECTION_HEAL_LOGS = "heal_logs"
COLLECTION_KNOWLEDGE = "test_knowledge"

ALL_COLLECTIONS = (
    COLLECTION_TESTCASES,
    COLLECTION_STEP_RESULTS,
    COLLECTION_HEAL_LOGS,
    COLLECTION_KNOWLEDGE,
)


# ============================================================
# 配置
# ============================================================
def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _enabled() -> bool:
    val = _env("RAG_ENABLED", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def _mode() -> str:
    return _env("QDRANT_MODE", "auto").strip().lower()


def _local_path() -> str:
    path = _env("QDRANT_LOCAL_PATH", "")
    if path:
        return path
    # platform/.qdrant_local
    return str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".qdrant_local"))


def score_threshold() -> float:
    try:
        return float(_env("RAG_SCORE_THRESHOLD", "0.0"))
    except ValueError:
        return 0.0


# ============================================================
# 客户端（懒加载单例，配置变化时重建）
# ============================================================
_store_lock = threading.Lock()
_client = None
_client_key: tuple | None = None
_degraded = False


def _build_client():
    """按模式构建 QdrantClient；auto 时远端不可达回退本地嵌入式。"""
    from qdrant_client import QdrantClient

    mode = _mode()
    url = _env("QDRANT_URL", "http://localhost:6333")
    api_key = _env("QDRANT_API_KEY") or None
    path = _local_path()

    if mode == "memory":
        return QdrantClient(":memory:")
    if mode == "local":
        return QdrantClient(path=path)
    if mode == "remote":
        return QdrantClient(url=url, api_key=api_key, timeout=5, check_compatibility=False)
    if mode == "off":
        return None

    # auto：先远端，失败回退本地嵌入式
    try:
        remote = QdrantClient(
            url=url, api_key=api_key, timeout=2, check_compatibility=False
        )
        remote.get_collections()
        return remote
    except Exception as exc:  # noqa: BLE001 - 降级路径
        logger.warning("Qdrant remote %s unavailable (%s); falling back to local store", url, exc)
        try:
            return QdrantClient(path=path)
        except Exception as exc2:  # noqa: BLE001
            logger.warning("Qdrant local store unavailable: %s", exc2)
            return None


def get_client():
    """返回单例客户端；不可用时返回 None（调用方降级）。"""
    global _client, _client_key, _degraded

    if not _enabled():
        return None

    key = (_mode(), _env("QDRANT_URL", "http://localhost:6333"), _local_path())
    with _store_lock:
        if _client is not None and _client_key == key:
            return _client
        if _client is not None:
            _close_client(_client)
        try:
            _client = _build_client()
        except ImportError:
            logger.warning("qdrant-client not installed; RAG retrieval disabled")
            _client = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant client init failed: %s", exc)
            _client = None
        _client_key = key
        _degraded = _client is None
        return _client


def _close_client(client) -> None:
    try:
        client.close()
    except Exception:  # noqa: BLE001
        pass


def _close_global_client() -> None:
    """进程退出前主动关闭，避免 qdrant-client local 在解释器关闭时报错。"""
    global _client
    try:
        if _client is not None:
            _close_client(_client)
            _client = None
    except Exception:  # noqa: BLE001
        pass


atexit.register(_close_global_client)


def reset_store() -> None:
    """测试用：关闭并清空客户端单例。"""
    global _client, _client_key, _degraded
    with _store_lock:
        if _client is not None:
            _close_client(_client)
        _client = None
        _client_key = None
        _degraded = False


def is_degraded() -> bool:
    return not _enabled() or _degraded


# ============================================================
# collection / upsert
# ============================================================
def ensure_collection(collection: str, dimension: int) -> bool:
    """确保 collection 存在且维度匹配；失败返回 False。"""
    client = get_client()
    if client is None:
        return False
    try:
        from qdrant_client.models import Distance, VectorParams

        existing = {c.name for c in client.get_collections().collections}
        if collection in existing:
            info = client.get_collection(collection)
            vectors = info.config.params.vectors
            size = getattr(vectors, "size", None)
            if size is None and isinstance(vectors, dict):
                size = next(iter(vectors.values())).size
            if size == dimension:
                return True
            logger.warning(
                "collection %s dim=%s != embedder dim=%s; recreating",
                collection, size, dimension,
            )
            client.delete_collection(collection)
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_collection(%s) failed: %s", collection, exc)
        return False


def upsert(collection: str, points: list[dict], dimension: int) -> bool:
    """写入向量点。

    points: [{"id": int, "vector": list[float], "payload": dict}]
    """
    if not points:
        return True
    if not ensure_collection(collection, dimension):
        return False
    client = get_client()
    if client is None:
        return False
    try:
        from qdrant_client.models import PointStruct

        client.upsert(
            collection_name=collection,
            points=[PointStruct(id=p["id"], vector=p["vector"], payload=p.get("payload", {})) for p in points],
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("upsert(%s, %d points) failed: %s", collection, len(points), exc)
        return False


# ============================================================
# 检索
# ============================================================
def retrieve(
    query: str,
    collection: str,
    top_k: int = 5,
    *,
    score_threshold_override: float | None = None,
    project_id: str = "",
) -> list[dict]:
    """向量检索，返回 [{id, payload, score}]（按 score 阈值过滤）。"""
    client = get_client()
    if client is None or not query:
        return []

    threshold = score_threshold() if score_threshold_override is None else score_threshold_override

    try:
        from apps.rag.embedder import get_embedder

        embedder = get_embedder()
        vector = embedder.embed(query)
        if not ensure_collection(collection, embedder.dimension):
            return []

        query_filter = None
        if project_id:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            query_filter = Filter(
                must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
            )

        result = client.query_points(
            collection_name=collection,
            query=vector,
            limit=max(1, int(top_k)),
            with_payload=True,
            query_filter=query_filter,
        )
        hits = getattr(result, "points", result) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieve(%s) failed: %s", collection, exc)
        return []

    out: list[dict] = []
    for hit in hits:
        score = float(getattr(hit, "score", 0.0) or 0.0)
        if threshold and score < threshold:
            continue
        out.append(
            {
                "id": getattr(hit, "id", None),
                "payload": getattr(hit, "payload", {}) or {},
                "score": score,
            }
        )
    return out


# ============================================================
# 业务方法
# ============================================================
def retrieve_similar_cases(goal: str, top_k: int = 3, project_id: str = "") -> list[dict]:
    """检索历史相似用例（用于 planner few-shot）。"""
    return retrieve(goal, COLLECTION_TESTCASES, top_k=top_k, project_id=project_id)


def retrieve_similar_failures(selector: str, error: str, top_k: int = 3) -> list[dict]:
    """检索历史同类失败（用于 analyzer）。"""
    query = " ".join(x for x in (selector, error) if x).strip()
    if not query:
        return []
    return retrieve(query, COLLECTION_STEP_RESULTS, top_k=top_k)


def retrieve_heal_experience(pattern: str, top_k: int = 3, only_successful: bool = True) -> list[dict]:
    """检索历史成功修复策略（用于 fixer）。"""
    if not pattern:
        return []
    results = retrieve(pattern, COLLECTION_HEAL_LOGS, top_k=max(top_k, top_k))
    if only_successful:
        results = [r for r in results if (r["payload"].get("success_count") or 0) > 0]
    return results[:top_k]


# ============================================================
# async 包装（供 async 节点使用）
# ============================================================
def retrieve_knowledge(query: str, top_k: int = 5, project_id: str = "") -> list[dict]:
    """检索知识库（PRD / 接口规范 / 业务规则）。空库或不可用时返回 []。"""
    return retrieve(query, COLLECTION_KNOWLEDGE, top_k=top_k, project_id=project_id)


async def aretrieve_similar_cases(goal: str, top_k: int = 3, project_id: str = "") -> list[dict]:
    from asgiref.sync import sync_to_async

    return await sync_to_async(retrieve_similar_cases, thread_sensitive=False)(
        goal, top_k=top_k, project_id=project_id
    )


async def aretrieve_knowledge(query: str, top_k: int = 5, project_id: str = "") -> list[dict]:
    from asgiref.sync import sync_to_async

    return await sync_to_async(retrieve_knowledge, thread_sensitive=False)(
        query, top_k=top_k, project_id=project_id
    )
