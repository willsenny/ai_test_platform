"""Phase J Step 4：RAG few-shot / 知识库 / 页面上下文注入测试。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class TestPromptInjection:
    def test_manual_prompt_includes_history_and_knowledge(self):
        from apps.agent.prompts import build_manual_prompt

        retrieved = [
            {"payload": {"title": "历史登录用例", "steps": [{"action": "click"}]}}
        ]
        knowledge = [{"content": "验证码 5 分钟有效", "score": 0.9}]
        prompt = build_manual_prompt(
            {"title": "登录"}, retrieved_cases=retrieved, knowledge=knowledge
        )
        assert "历史登录用例" in prompt
        assert "验证码 5 分钟有效" in prompt

    def test_ui_prompt_includes_page_elements(self):
        from apps.agent.prompts import build_ui_prompt

        snapshot = {
            "title": "Demo Login",
            "elements": [{"tag": "input", "id": "phone", "placeholder": "手机号"}],
        }
        prompt = build_ui_prompt({"title": "登录"}, "http://x", page_snapshot=snapshot)
        assert "Demo Login" in prompt
        assert '"id": "phone"' in prompt

    def test_no_extras_keeps_prompt_clean(self):
        from apps.agent.prompts import build_manual_prompt

        prompt = build_manual_prompt({"title": "登录"})
        assert "历史相似用例" not in prompt
        assert "相关知识" not in prompt


class TestPlannerKnowledge:
    @pytest.mark.asyncio
    async def test_planner_retrieves_knowledge(self, monkeypatch):
        monkeypatch.setattr(
            "apps.rag.retriever.aretrieve_similar_cases",
            AsyncMock(return_value=[{"payload": {"title": "历史"}}]),
        )
        monkeypatch.setattr(
            "apps.rag.retriever.aretrieve_knowledge",
            AsyncMock(return_value=[{"content": "规则A"}]),
        )
        from apps.agent.graph import planner_node

        result = await planner_node({"requirement": "登录", "project_id": "demo"})
        assert result["retrieved_knowledge"] == [{"content": "规则A"}]
        assert any("知识库" in line for line in result["plan"])

    @pytest.mark.asyncio
    async def test_planner_knowledge_failure_does_not_break(self, monkeypatch):
        monkeypatch.setattr(
            "apps.rag.retriever.aretrieve_similar_cases",
            AsyncMock(return_value=[]),
        )

        async def boom(*args, **kwargs):
            raise RuntimeError("qdrant down")

        monkeypatch.setattr("apps.rag.retriever.aretrieve_knowledge", boom)
        from apps.agent.graph import planner_node

        result = await planner_node({"requirement": "登录", "project_id": "demo"})
        assert result["retrieved_knowledge"] == []


class TestGenerateInjectsRag:
    @pytest.mark.asyncio
    async def test_generate_for_scenario_forwards_context(self, monkeypatch):
        from apps.agent import generation

        captured = {}

        async def fake_structured(config, prompt, schema, **kwargs):
            captured["prompt"] = prompt
            return schema.model_validate({"cases": []}), {}, 0

        monkeypatch.setattr(
            generation, "route",
            lambda task: SimpleNamespace(model="m", reasoning_effort=None),
        )
        monkeypatch.setattr(generation, "record_llm_call", AsyncMock())
        monkeypatch.setattr(generation, "call_structured", fake_structured)

        await generation.generate_for_scenario(
            {"title": "登录", "automation": {"manual": True, "ui": False, "api": False}},
            retrieved_cases=[{"payload": {"title": "历史用例X", "steps": []}}],
            knowledge=[{"content": "知识片段Y"}],
        )
        assert "历史用例X" in captured["prompt"]
        assert "知识片段Y" in captured["prompt"]


class TestRetrieverKnowledge:
    def test_retrieve_knowledge_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setenv("RAG_ENABLED", "0")
        from apps.rag.retriever import reset_store, retrieve_knowledge

        reset_store()
        assert retrieve_knowledge("登录") == []
        reset_store()

    def test_collection_constant(self):
        from apps.rag.retriever import COLLECTION_KNOWLEDGE

        assert COLLECTION_KNOWLEDGE == "test_knowledge"
