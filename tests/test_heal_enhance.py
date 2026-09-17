"""Phase J Step 6：自愈增强（向量定位器库 + LLM 候选 + API 断言自愈）测试。"""
from types import SimpleNamespace

import pytest


class TestSelectorExtraction:
    def test_extract_present_candidate(self):
        from apps.selfheal.fixer import _extract_selector

        candidates = ["#phone", "#code", 'button:has-text("登录")']
        assert _extract_selector('建议使用 "#code"', candidates) == "#code"

    def test_extract_none(self):
        from apps.selfheal.fixer import _extract_selector

        assert _extract_selector("无法判断", ["#phone"]) == ""

    def test_candidate_selectors_dedup(self):
        from apps.selfheal.fixer import _candidate_selectors

        elements = [
            {"id": "phone"}, {"id": "phone"}, {"name": "code"},
        ]
        assert _candidate_selectors(elements) == ["#phone", '[name="code"]']


class TestFindSimilarKey:
    def test_renamed_field(self):
        from apps.selfheal.fixer import _find_similar_key

        assert _find_similar_key({"username": "x"}, "data.username") == "username"

    def test_no_match(self):
        from apps.selfheal.fixer import _find_similar_key

        assert _find_similar_key({"other": 1}, "data.token") is None

    def test_non_dict_body(self):
        from apps.selfheal.fixer import _find_similar_key

        assert _find_similar_key(["a"], "token") is None


class TestApiAssertionFix:
    @pytest.mark.asyncio
    async def test_refresh_expected(self):
        from apps.selfheal.fixer import _fix_api_assertion

        case = SimpleNamespace(assertions=[{"type": "json_field", "path": "code", "expected": 1}])
        feature = SimpleNamespace(
            action="json_field", selector="code", expected="1", actual="0",
            failure_type="text_mismatch",
        )
        result = await _fix_api_assertion(case, feature)
        assert result.success is True
        assert result.strategy == "assertion_refresh"
        assert case.assertions[0]["expected"] == "0"

    @pytest.mark.asyncio
    async def test_field_rename(self):
        from apps.selfheal.fixer import _fix_api_assertion

        case = SimpleNamespace(
            assertions=[{"type": "json_path_exists", "path": "data.token"}]
        )
        feature = SimpleNamespace(
            action="json_path_exists", selector="data.token", expected="",
            actual='{"token": "abc"}', failure_type="text_mismatch",
        )
        result = await _fix_api_assertion(case, feature)
        assert result.success is True
        assert result.strategy == "field_rename"
        assert case.assertions[0]["path"] == "token"

    @pytest.mark.asyncio
    async def test_no_match(self):
        from apps.selfheal.fixer import _fix_api_assertion

        case = SimpleNamespace(assertions=[{"type": "json_schema", "schema": {}}])
        feature = SimpleNamespace(
            action="json_schema", selector="", expected="", actual="{}",
            failure_type="text_mismatch",
        )
        result = await _fix_api_assertion(case, feature)
        assert result.success is False


class TestLocatorLibrary:
    def test_collection_constant(self):
        from apps.rag.retriever import COLLECTION_LOCATORS

        assert COLLECTION_LOCATORS == "locator_history"

    def test_retrieve_locator_disabled(self, monkeypatch):
        monkeypatch.setenv("RAG_ENABLED", "0")
        from apps.rag.retriever import reset_store, retrieve_locator

        reset_store()
        assert retrieve_locator("#code_old", "not found", "http://x") == []
        reset_store()

    def test_index_locator_disabled(self, monkeypatch):
        monkeypatch.setenv("RAG_ENABLED", "0")
        from apps.rag.indexer import index_locator
        from apps.rag.retriever import reset_store

        reset_store()
        assert index_locator("#a", "http://x", "#b") is False
        reset_store()
