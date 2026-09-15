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
    @patch("apps.agent.nodes.call_llm")
    async def test_requirement_to_testcases(self, mock_llm):
        """需求 → 生成测试用例 → 代码"""
        from apps.agent.graph import run_test_workflow

        # Mock LLM 响应
        mock_llm.return_value = {"content": "[]"}

        result = await run_test_workflow(
            requirement="用户登录：手机号+验证码",
            project_id="demo",
            retry_budget=1,
        )

        assert result is not None
        assert "final_status" in result

    @pytest.mark.asyncio
    @patch("apps.mcp.client.MCPClient.call_tool")
    async def test_self_heal_flow(self, mock_call_tool):
        """自愈五段闭环"""
        from apps.selfheal.engine import SelfHealEngine, FailureContext

        # Mock: 第一次规则修复失败，第二次向量成功
        mock_call_tool.return_value = '{"summary": {"failed": 0}}'

        engine = SelfHealEngine(retry_budget=3)
        failure = FailureContext(
            test_id="login_001",
            error_message="TimeoutError: waiting for #submit",
            locator="#submit-btn",
            page_url="https://example.com/login",
        )

        result = await engine.heal(failure)

        # 验证自愈结果结构
        assert hasattr(result, "success")
        assert hasattr(result, "strategy")
        assert hasattr(result, "retries")

    @pytest.mark.asyncio
    async def test_cost_tracker(self):
        """成本追踪"""
        from apps.agent.router import get_cost_tracker, route, ModelTier

        tracker = get_cost_tracker()
        cfg = route("generate_testcase")  # L1

        tracker.record(cfg.tier, 1000, 500)

        assert tracker.usage[ModelTier.L1_FLASH]["calls"] == 1
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
    @patch("apps.rag.service.embed")
    async def test_retrieve_empty(self, mock_embed):
        """空库检索返回空"""
        from apps.rag.service import retrieve

        mock_embed.return_value = [[0.0] * 1024]

        results = await retrieve("test query")
        assert results == []


class TestModelRouter:
    """模型路由测试"""

    def test_default_is_flash(self):
        from apps.agent.router import route, ModelTier
        cfg = route("generate_testcase")
        assert cfg.tier == ModelTier.L1_FLASH

    def test_complex_uses_pro(self):
        from apps.agent.router import route, ModelTier
        cfg = route("refactor_code")
        assert cfg.tier == ModelTier.L2_PRO

    def test_self_heal_uses_sonnet(self):
        from apps.agent.router import route, ModelTier
        cfg = route("self_heal_repair")
        assert cfg.tier == ModelTier.L3_SONNET

    def test_force_tier(self):
        from apps.agent.router import route, ModelTier
        cfg = route("anything", force_tier=ModelTier.L3_SONNET)
        assert cfg.tier == ModelTier.L3_SONNET


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
