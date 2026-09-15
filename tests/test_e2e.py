"""
端到端集成测试

模拟完整工作流：
  需求 → RAG 检索 → LangGraph 生成 → 执行 → 自愈 → PR

运行:
  pytest tests/test_e2e.py -v
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock


@pytest.fixture
def event_loop():
    """为每个测试创建新的事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestFullWorkflow:
    """完整工作流测试（Mock LLM 调用）"""

    @pytest.mark.asyncio
    @patch("apps.rag.service.retrieve", new_callable=AsyncMock)
    async def test_requirement_to_testcases(self, mock_retrieve, monkeypatch):
        """需求 → 生成测试用例 → 代码"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        mock_retrieve.return_value = []

        from apps.agent.graph import run_test_workflow

        result = await run_test_workflow(
            requirement="用户登录：手机号+验证码",
            project_id="demo",
            retry_budget=1,
        )

        assert result is not None
        assert "final_status" in result

    @pytest.mark.asyncio
    @patch("apps.mcp.client.MCPClient.call_tool")
    async def test_self_heal_flow(self, mock_call_tool, monkeypatch):
        """自愈五段闭环"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from apps.selfheal.engine import SelfHealEngine, FailureContext

        # Mock: 第一次规则修复失败，第二次向量成功
        mock_call_tool.return_value = '{"summary": {"failed": 0}}'

        engine = SelfHealEngine(retry_budget=3)
        failure = FailureContext(
            test_id="login_001",
            error_message="TimeoutError: waiting for #submit",
            stack_trace="",
            locator="#submit-btn",
            page_url="https://example.com/login",
        )

        result = await engine.heal(failure)

        # 验证自愈结果结构
        assert hasattr(result, "success")
        assert hasattr(result, "strategy")
        assert hasattr(result, "retries")

    @pytest.mark.asyncio
    async def test_cost_tracker(self, monkeypatch):
        """成本追踪（Flash-Only）"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from apps.agent.router import get_cost_tracker, route

        tracker = get_cost_tracker()
        route("generate_testcase")  # Flash (low)

        calls_before = tracker.calls
        tokens_before = tracker.input_tokens
        tracker.record(1000, 500)

        assert tracker.calls == calls_before + 1
        assert tracker.input_tokens == tokens_before + 1000
        assert tracker.total_usd() > 0


class TestRAG:
    """RAG 服务测试"""

    @pytest.mark.asyncio
    async def test_text_splitting(self):
        """文本分块"""
        from apps.rag.service import _split_text

        text = "A" * 1200
        chunks = _split_text(text, chunk_size=500, overlap=50)

        assert len(chunks) > 1
        assert all(len(c) <= 500 for c in chunks)

    @pytest.mark.asyncio
    @patch("apps.rag.service._get_qdrant")
    @patch("apps.rag.service.ensure_collection", new_callable=AsyncMock)
    @patch("apps.rag.service.embed")
    async def test_retrieve_empty(self, mock_embed, mock_ensure, mock_qdrant):
        """空库检索返回空"""
        from apps.rag.service import retrieve

        mock_embed.return_value = [[0.0] * 1024]
        mock_client = AsyncMock()
        mock_client.search.return_value = []
        mock_qdrant.return_value = mock_client

        results = await retrieve("test query")
        assert results == []


class TestModelRouter:
    """模型路由测试（Flash-Only + reasoning 档位）"""

    def test_default_is_flash_low(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from apps.agent.router import route
        cfg = route("generate_testcase")
        assert cfg.model == "deepseek-flash"
        assert cfg.reasoning_effort is None

    def test_complex_uses_high_reasoning(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from apps.agent.router import route
        cfg = route("refactor_code")
        assert cfg.model == "deepseek-flash"
        assert cfg.reasoning_effort == "high"

    def test_self_heal_uses_high_reasoning(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from apps.agent.router import route
        cfg = route("self_heal_repair")
        assert cfg.reasoning_effort == "high"

    def test_force_reasoning(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        from apps.agent.router import route, ReasoningLevel
        cfg = route("anything", force_reasoning=ReasoningLevel.HIGH)
        assert cfg.reasoning_effort == "high"

    def test_local_fallback(self):
        from apps.agent.router import route
        cfg = route("anything", use_local=True)
        assert cfg.source == "local-ollama"

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        from apps.agent.router import get_config, ReasoningLevel
        with pytest.raises(RuntimeError):
            get_config(ReasoningLevel.LOW)


class TestMCPClient:
    """MCP 客户端测试"""

    def test_config_loading(self):
        """加载 MCP 配置"""
        import json
        from pathlib import Path

        config_path = Path(__file__).parent.parent / "platform" / "apps" / "mcp" / "config.json"
        assert config_path.exists()

        with open(config_path) as f:
            config = json.load(f)

        # 验证 Playwright stdio 配置
        assert "playwright" in config
        assert config["playwright"]["transport"] == "stdio"

        # 验证 WHartTest SSE 兼容
        assert "wharttest_tools" in config
        assert config["wharttest_tools"]["transport"] == "sse"


class TestSelfHealRules:
    """Phase F 规则自愈：失败分类 + selector 模糊匹配"""

    def test_classify_selector(self):
        from apps.selfheal.analyzer import classify

        error = (
            "TimeoutError: Page.fill: Timeout 1000ms exceeded.\n"
            "Call log:\n  - waiting for locator(\"#code_old\")"
        )
        assert classify("step", "", "", error)[0] == "element_not_found"

    def test_classify_assertion(self):
        from apps.selfheal.analyzer import classify

        assert classify("assert", "登录OK", "登录成功", "")[0] == "text_mismatch"

    def test_classify_timing(self):
        from apps.selfheal.analyzer import classify

        error = (
            "locator.click: Timeout 1000ms exceeded. Call log: "
            "- waiting for element to be visible, enabled and stable"
        )
        assert classify("step", "", "", error)[0] == "timeout"

    def test_classify_navigation(self):
        from apps.selfheal.analyzer import classify

        assert classify("step", "", "", "net::ERR_CONNECTION_REFUSED")[0] == "navigation_failed"

    def test_selector_fuzzy_match(self):
        from apps.selfheal.fixer import _best_match, _selector_for, _tokens

        elements = [
            {"id": "phone", "name": "phone", "placeholder": "手机号"},
            {"id": "code", "name": "code", "placeholder": "验证码"},
        ]
        best, score = _best_match(elements, _tokens("#code_old"))
        assert score >= 1
        assert _selector_for(best) == "#code"
