"""Phase J Step 1：Jira Story 解析器测试（纯 Python，不依赖 DB）。"""
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "story_requirements.md"


class TestStoryParser:
    def _scenarios(self):
        from apps.core.parsers import get_parser

        text = FIXTURE.read_text(encoding="utf-8")
        parser = get_parser("md", text)
        assert parser.__class__.__name__ == "StoryParser"
        return parser.parse(text)

    def test_two_stories(self):
        scenarios = self._scenarios()
        assert len(scenarios) == 2
        assert scenarios[0]["story_key"] == "ACC-101"
        assert scenarios[1]["story_key"] == "ACC-102"

    def test_epic_sprint_module(self):
        first = self._scenarios()[0]
        assert first["epic"] == "用户账户体系"
        assert first["sprint"] == "2026-S1"
        assert first["module"] == "登录"

    def test_types_and_primary(self):
        first, second = self._scenarios()
        assert first["test_types"] == ["functional", "ui", "api"]
        assert first["type"] == "ui"
        assert second["test_types"] == ["functional"]
        assert second["type"] == "functional"

    def test_priority_and_story_points(self):
        first = self._scenarios()[0]
        assert first["priority"] == "P0"
        assert first["story_points"] == 5

    def test_gherkin_acceptance(self):
        first = self._scenarios()[0]
        names = [a["name"] for a in first["acceptance"]]
        assert names == ["正常登录", "验证码错误"]
        normal = first["acceptance"][0]
        assert normal["given"] == ["用户在登录页"]
        assert len(normal["when"]) == 2
        assert normal["then"] == ['页面提示 "登录成功"']

    def test_automation_flags(self):
        first, second = self._scenarios()
        assert first["automation"] == {"manual": True, "ui": True, "api": True}
        assert second["automation"] == {"manual": True, "ui": False, "api": False}

    def test_business_rules_test_data_tags(self):
        first = self._scenarios()[0]
        assert first["business_rules"] == ["验证码 5 分钟有效", "连续错误 5 次锁定 10 分钟"]
        assert first["test_data"]["手机号"] == "13800138000"
        assert first["test_data"]["验证码"] == "123456"
        assert first["tags"] == ["login", "smoke"]

    def test_api_ref_and_env(self):
        first, second = self._scenarios()
        assert first["api_ref"] == "POST /api/login"
        assert second["api_ref"] == ""
        assert first["env"]["swagger"].endswith("/v3/api-docs")

    def test_role_goal_benefit(self):
        first = self._scenarios()[0]
        assert first["role"] == "已注册用户"
        assert first["goal"] == "使用手机号+验证码登录"
        assert first["benefit"] == "我可以访问个人中心"


class TestFactorySelection:
    def test_story_text_selects_story_parser(self):
        from apps.core.parsers import StoryParser, get_parser

        text = FIXTURE.read_text(encoding="utf-8")
        assert isinstance(get_parser("md", text), StoryParser)

    def test_plain_markdown_selects_markdown_parser(self):
        from apps.core.parsers import MarkdownParser, get_parser

        text = "## 场景一：登录\n用户输入手机号。\n"
        assert isinstance(get_parser("md", text), MarkdownParser)

    def test_unsupported_type_still_raises(self):
        from apps.core.parsers import get_parser

        try:
            get_parser("pdf", "### Story: X")
        except ValueError:
            return
        raise AssertionError("expected ValueError for unsupported type")
