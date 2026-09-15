"""
Embedder 抽象（Phase G）

统一接口：embed(text) -> list[float]
- FakeEmbedder：开发用，dim=8 的确定性哈希词袋向量，不依赖任何模型/网络。
- BGEEmbedder：生产用，调用 OpenAI 兼容的 embeddings HTTP 接口
  （bge-m3 / text2vec-large-chinese 等），维度按模型返回自动探测。

选择：环境变量 RAG_EMBEDDER=fake|bge（默认 fake）。
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """向量化接口协议。"""

    dimension: int

    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        ...


# ============================================================
# 开发用：确定性哈希词袋向量（dim=8）
# ============================================================
_TOKEN_RE = re.compile(r"[0-9a-zA-Z]+|[\u4e00-\u9fff]")


def _tokenize(text: str) -> list[str]:
    """把文本切成 token；中文按单字 + 相邻二元组，英文数字按词。"""
    text = (text or "").lower()
    raw = _TOKEN_RE.findall(text)
    tokens: list[str] = list(raw)
    cjk = [t for t in raw if len(t) == 1 and "\u4e00" <= t <= "\u9fff"]
    for a, b in zip(cjk, cjk[1:]):
        tokens.append(a + b)
    return tokens


def _normalize(vec: list[float]) -> list[float]:
    norm = sum(v * v for v in vec) ** 0.5
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


class FakeEmbedder:
    """开发用向量器。

    对每个 token 做 md5 哈希映射到 dimension 维桶并累加（带符号），
    最后 L2 归一化。相同文本得到相同向量；共享 token 的文本余弦相似度更高，
    因此无需真实模型即可演示检索。默认 dimension=8。
    """

    def __init__(self, dimension: int = 8):
        self.dimension = max(1, int(dimension))

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = _tokenize(text)
        if not tokens:
            tokens = [text or ""]
        for tok in tokens:
            digest = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = digest % self.dimension
            sign = 1.0 if (digest >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
        return _normalize(vec)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


# ============================================================
# 生产用：BGE / 任意 OpenAI 兼容 embeddings 服务
# ============================================================
class BGEEmbedder:
    """调用 OpenAI 兼容接口生成嵌入。

    推荐模型：BAAI/bge-m3 或 shibing624/text2vec-large-chinese（dim=1024）。
    服务不可用时抛异常，由上层（retriever/indexer）降级处理。
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        dimension: int = 1024,
    ):
        self.model = model or os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
        self.base_url = (base_url or os.getenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1")).rstrip("/")
        self.api_key = api_key or os.getenv("EMBEDDING_API_KEY", "EMPTY")
        self.dimension = int(os.getenv("EMBEDDING_DIM", dimension))

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        import httpx

        resp = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model, "input": texts},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        vectors = [item["embedding"] for item in data["data"]]
        if vectors:
            self.dimension = len(vectors[0])
        return vectors


# ============================================================
# 工厂
# ============================================================
_embedder: Embedder | None = None
_embedder_key: tuple | None = None


def get_embedder() -> Embedder:
    """按环境变量返回单例 Embedder（fake|bge）。"""
    global _embedder, _embedder_key

    kind = os.getenv("RAG_EMBEDDER", "fake").strip().lower()
    key = (kind, os.getenv("RAG_FAKE_DIM", "8"), os.getenv("EMBEDDING_DIM", "1024"))
    if _embedder is not None and _embedder_key == key:
        return _embedder

    if kind == "bge":
        _embedder = BGEEmbedder()
    else:
        _embedder = FakeEmbedder(dimension=int(os.getenv("RAG_FAKE_DIM", "8")))
    _embedder_key = key
    return _embedder


def reset_embedder() -> None:
    """测试用：清空单例。"""
    global _embedder, _embedder_key
    _embedder = None
    _embedder_key = None
