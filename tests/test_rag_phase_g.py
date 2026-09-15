"""
Phase G — RAG 检索增强测试

覆盖：
- Embedder 抽象（FakeEmbedder 维度/确定性/相似性、工厂）
- Retriever 三业务方法 roundtrip
- Qdrant 不可用/关闭时降级返回空
- planner 注入历史相似用例（few-shot）
- fixer 命中历史成功修复经验
- echo server 复用历史 selector
"""
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@pytest.fixture
def rag_env(monkeypatch):
    """每个测试使用全新内存 Qdrant + FakeEmbedder。"""
    monkeypatch.setenv("RAG_ENABLED", "1")
    monkeypatch.setenv("QDRANT_MODE", "memory")
    monkeypatch.setenv("RAG_EMBEDDER", "fake")
    monkeypatch.setenv("RAG_FAKE_DIM", "8")
    monkeypatch.setenv("RAG_SCORE_THRESHOLD", "0.0")

    from apps.rag.embedder import reset_embedder
    from apps.rag.retriever import reset_store

    reset_embedder()
    reset_store()
    yield
    reset_embedder()
    reset_store()


class TestEmbedder:
    def test_fake_dim_and_deterministic(self):
        from apps.rag.embedder import FakeEmbedder

        e = FakeEmbedder(dimension=8)
        a1 = e.embed("用户登录 验证码")
        a2 = e.embed("用户登录 验证码")
        assert len(a1) == 8
        assert a1 == a2

    def test_fake_semantic_overlap(self):
        from apps.rag.embedder import FakeEmbedder

        e = FakeEmbedder(dimension=8)
        base = "用户登录 手机号 验证码"
        similar = _cos(e.embed(base), e.embed("用户登录 验证码"))
        different = _cos(e.embed(base), e.embed("购物车 结算 订单"))
        assert similar > different

    def test_factory_selects_fake(self, monkeypatch):
        monkeypatch.setenv("RAG_EMBEDDER", "fake")
        monkeypatch.setenv("RAG_FAKE_DIM", "8")
        from apps.rag.embedder import FakeEmbedder, get_embedder, reset_embedder

        reset_embedder()
        assert isinstance(get_embedder(), FakeEmbedder)
        assert get_embedder().dimension == 8


class TestRetriever:
    def test_similar_cases_roundtrip(self, rag_env):
        from apps.rag.embedder import get_embedder
        from apps.rag.retriever import (
            COLLECTION_TESTCASES,
            retrieve_similar_cases,
            upsert,
        )

        e = get_embedder()
        cases = [
            (1, "用户登录 正常流程 #phone #code #submit 登录成功"),
            (2, "购物车 结算 订单 支付"),
        ]
        for cid, text in cases:
            upsert(
                COLLECTION_TESTCASES,
                [
                    {
                        "id": cid,
                        "vector": e.embed(text),
                        "payload": {"title": text, "project_id": "demo", "steps": []},
                    }
                ],
                e.dimension,
            )

        hits = retrieve_similar_cases("用户登录 #code", top_k=3, project_id="demo")
        assert hits and hits[0]["id"] == 1
        assert hits[0]["payload"]["title"].startswith("用户登录")
        assert hits[0]["score"] > 0

    def test_similar_failures(self, rag_env):
        from apps.rag.embedder import get_embedder
        from apps.rag.retriever import (
            COLLECTION_STEP_RESULTS,
            retrieve_similar_failures,
            upsert,
        )

        e = get_embedder()
        upsert(
            COLLECTION_STEP_RESULTS,
            [
                {
                    "id": 11,
                    "vector": e.embed("#code element_not_found waiting for locator #code_old"),
                    "payload": {"selector": "#code", "error": "waiting for locator #code_old"},
                }
            ],
            e.dimension,
        )
        hits = retrieve_similar_failures("#code", "waiting for locator #code_old")
        assert hits and hits[0]["payload"]["selector"] == "#code"

    def test_heal_experience_filters_success(self, rag_env):
        from apps.rag.embedder import get_embedder
        from apps.rag.retriever import (
            COLLECTION_HEAL_LOGS,
            retrieve_heal_experience,
            upsert,
        )

        e = get_embedder()
        upsert(
            COLLECTION_HEAL_LOGS,
            [
                {
                    "id": 21,
                    "vector": e.embed("element_not_found selector_remap"),
                    "payload": {
                        "failure_pattern": "element_not_found",
                        "fix_strategy": "selector_remap",
                        "success_count": 1,
                        "success_rate": 1.0,
                    },
                },
                {
                    "id": 22,
                    "vector": e.embed("timeout timing_wait"),
                    "payload": {
                        "failure_pattern": "timeout",
                        "fix_strategy": "timing_wait",
                        "success_count": 0,
                        "success_rate": 0.0,
                    },
                },
            ],
            e.dimension,
        )
        hits = retrieve_heal_experience("element_not_found", only_successful=True)
        assert hits and hits[0]["payload"]["fix_strategy"] == "selector_remap"


class TestDegradation:
    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setenv("RAG_ENABLED", "0")
        monkeypatch.setenv("QDRANT_MODE", "memory")
        from apps.rag.retriever import is_degraded, reset_store, retrieve_similar_cases

        reset_store()
        assert retrieve_similar_cases("login") == []
        assert is_degraded() is True

    def test_remote_unreachable_returns_empty(self, monkeypatch):
        monkeypatch.setenv("RAG_ENABLED", "1")
        monkeypatch.setenv("QDRANT_MODE", "remote")
        monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:59999")
        from apps.rag.retriever import (
            reset_store,
            retrieve_similar_cases,
            retrieve_similar_failures,
        )

        reset_store()
        assert retrieve_similar_cases("login") == []
        assert retrieve_similar_failures("#code", "timeout") == []


class TestPlannerInjection:
    @pytest.mark.asyncio
    async def test_planner_retrieves_cases_and_logs(self, monkeypatch):
        fake_hits = [
            {"id": 1, "payload": {"title": "用户登录 - 正常流程", "steps": []}, "score": 0.9},
            {"id": 2, "payload": {"title": "用户登录 - 边界条件", "steps": []}, "score": 0.7},
        ]
        monkeypatch.setattr(
            "apps.rag.retriever.aretrieve_similar_cases",
            AsyncMock(return_value=fake_hits),
        )

        from apps.agent.graph import planner_node

        result = await planner_node({"requirement": "用户登录", "project_id": "demo"})
        assert result["retrieved_cases"] == fake_hits
        assert any("[retrieved 2 similar cases]" in line for line in result["plan"])


class TestFixerExperience:
    def test_heal_experience_maps_unknown_to_known_strategy(self, monkeypatch):
        hits = [
            {
                "id": 1,
                "payload": {
                    "failure_pattern": "element_not_found",
                    "fix_strategy": "timing_wait",
                    "success_rate": 1.0,
                },
                "score": 0.9,
            }
        ]
        monkeypatch.setattr(
            "apps.rag.retriever.retrieve_heal_experience", lambda *a, **k: hits
        )
        from apps.selfheal.fixer import _heal_experience

        hint, mapped = _heal_experience("unknown")
        assert mapped == "timeout"
        assert "timing_wait" in hint

    def test_no_experience_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "apps.rag.retriever.retrieve_heal_experience", lambda *a, **k: []
        )
        from apps.selfheal.fixer import _heal_experience

        hint, mapped = _heal_experience("element_not_found")
        assert hint == "" and mapped is None


class TestIndexer:
    def test_index_testcase_and_retrieve(self, rag_env):
        from apps.rag.indexer import index_testcase
        from apps.rag.retriever import retrieve_similar_cases

        case = SimpleNamespace(
            pk=101,
            title="用户登录 正常流程",
            project_id="demo",
            priority="P0",
            tags=["login"],
            target_url="",
            source="test",
            raw_steps=[
                {"action": "fill", "selector": "#code_reused", "value": "123456", "description": "验证码"}
            ],
            steps=[],
            assertions=[{"type": "text_contains", "selector": "#result", "expected": "登录成功"}],
        )
        assert index_testcase(case) is True

        hits = retrieve_similar_cases("用户登录 #code", project_id="demo")
        assert hits and hits[0]["payload"]["steps"][0]["selector"] == "#code_reused"


class TestEchoFewShot:
    def test_reuses_historical_selectors(self):
        import sys

        sys.path.insert(0, str(REPO_ROOT))
        try:
            from mcp_servers.echo_server import _extract_selectors
        except Exception as exc:  # pragma: no cover - 环境缺 mcp 时跳过
            pytest.skip(f"echo_server import failed: {exc}")

        few_shot = (
            '[{"title":"历史","steps":['
            '{"action":"fill","selector":"#phone_v2","description":"手机号"},'
            '{"action":"fill","selector":"#code_v2","description":"验证码"},'
            '{"action":"click","selector":"#submit_v2","description":"登录"}]}]'
        )
        found = _extract_selectors(few_shot)
        assert found["phone"] == "#phone_v2"
        assert found["code"] == "#code_v2"
        assert found["submit"] == "#submit_v2"
