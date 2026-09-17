"""
Jira Sprint Story 解析器（Phase J）。

输入 Jira 风格需求文档（Epic / Sprint / Story + As a/I want/So that + Gherkin AC），
输出结构化场景，供 LLM 生成 手动用例 / UI 自动化 / 接口自动化。

输出结构（list[dict]）：
    {
        "title", "story_key", "epic", "sprint", "module",
        "test_types": ["functional","ui","api"],
        "type": "ui"|"api"|"functional",       # 主类型（兼容旧生成链）
        "priority", "story_points",
        "role", "goal", "benefit",
        "business_rules": [str], "test_data": {k:v},
        "acceptance": [{"name", "given", "when", "then", "steps"}],
        "definition_of_done": [str],
        "automation": {"manual","ui","api"},
        "api_ref", "tags",
        "env": {"ui","api","swagger"},
        "description", "acceptance_criteria": [str],
        "raw_text",
    }
"""
import re

from .base import BaseParser

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_ENV_RE = re.compile(r"^\s*>\s*(UI|API|Swagger|UI地址|API地址|Swagger地址)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)
_EPIC_RE = re.compile(r"^#\s*(?:Epic\s*[:：]\s*)?(.+?)\s*$", re.IGNORECASE)
_SPRINT_RE = re.compile(r"^##\s*Sprint\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)
_STORY_RE = re.compile(r"^###\s*Story\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)
_META_RE = re.compile(
    r"^\s*[-*]\s*(类型|优先级|Story\s*Points|组件|标签|自动化|关联接口)\s*[:：]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_BOLD_SECTION_RE = re.compile(r"^\s*\*\*(.+?)\*\*\s*$")
_GHERKIN_FENCE_RE = re.compile(r"```(?:gherkin|feature|text)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_SCENARIO_RE = re.compile(r"^(?:Scenario|场景)\s*[:：]\s*(.*)$", re.IGNORECASE)
_STEP_RE = re.compile(
    r"^(Given|When|Then|And|But|假如|当|那么|并且|而且)\b\s*(.*)$", re.IGNORECASE
)
_STORY_KEY_RE = re.compile(r"^\s*([A-Z][A-Z0-9]+-\d+)\s+(.*)$")

_PRIORITY_MAP = {
    "HIGHEST": "P0", "HIGH": "P1", "MEDIUM": "P2", "LOW": "P2",
    "P0": "P0", "P1": "P1", "P2": "P2",
    "最高": "P0", "高": "P0", "中": "P1", "低": "P2",
}
_TYPE_MAP = {
    "功能": "functional", "functional": "functional", "function": "functional",
    "ui": "ui", "界面": "ui",
    "接口": "api", "api": "api", "interface": "api",
}
_TRUE_VALUES = {"是", "yes", "true", "1", "y", "on"}
_FALSE_VALUES = {"否", "no", "false", "0", "n", "off", "无", ""}

_STORY_MARKERS = re.compile(
    r"(###\s*Story|Acceptance\s*Criteria|\*\*As a\*\*|```gherkin)", re.IGNORECASE
)


def looks_like_story(text: str) -> bool:
    return bool(_STORY_MARKERS.search(text or ""))


class StoryParser(BaseParser):
    """Jira Sprint Story → 结构化场景。"""

    file_type = "story"
    FILETYPES = {"md", "markdown", "story", "txt", "text"}

    @classmethod
    def supports(cls, file_type: str) -> bool:
        return (file_type or "").strip().lower().lstrip(".") in cls.FILETYPES

    # --------------------------------------------------------
    def parse(self, text: str) -> list[dict]:
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        env = self._parse_env(text)
        epic = self._parse_epic(text)
        blocks = self._split_stories(text)
        scenarios = [
            self._build_story(title, body, epic, env, sprint)
            for title, sprint, body in blocks
        ]
        return [s for s in scenarios if s]

    # --------------------------------------------------------
    @staticmethod
    def _parse_env(text: str) -> dict:
        env = {"ui": "", "api": "", "swagger": ""}
        for line in text.split("\n"):
            match = _ENV_RE.match(line)
            if not match:
                continue
            key = match.group(1).lower().replace("地址", "")
            if key in env:
                env[key] = match.group(2).strip()
        return env

    @staticmethod
    def _parse_epic(text: str) -> str:
        for line in text.split("\n"):
            match = _EPIC_RE.match(line)
            if match:
                value = match.group(1).strip()
                if value.lower().startswith("epic"):
                    value = value.split(":", 1)[-1].strip()
                return value
        return ""

    def _split_stories(self, text: str) -> list[tuple[str, str, str]]:
        """返回 [(story_title, sprint, body)]。"""
        stories: list[tuple[str, str, list[str]]] = []
        sprint = ""
        in_code = False
        for line in text.split("\n"):
            if line.strip().startswith("```"):
                in_code = not in_code
            if not in_code:
                sprint_match = _SPRINT_RE.match(line)
                if sprint_match:
                    sprint = sprint_match.group(1).strip()
                story_match = _STORY_RE.match(line)
                if story_match:
                    stories.append((story_match.group(1).strip(), sprint, []))
                    continue
            if stories:
                stories[-1][2].append(line)
        return [(title, sp, "\n".join(body).strip()) for title, sp, body in stories]

    # --------------------------------------------------------
    def _build_story(self, title: str, body: str, epic: str, env: dict, sprint: str = "") -> dict:
        story_key, story_title = self._split_key(title)
        meta = self._parse_meta(body)
        sections = self._split_bold_sections(body)

        test_types = self._parse_types(meta.get("类型", ""))
        primary = "ui" if "ui" in test_types else ("api" if "api" in test_types else "functional")
        priority = _PRIORITY_MAP.get(meta.get("优先级", "").upper(), _PRIORITY_MAP.get(meta.get("优先级", ""), "P1"))

        automation = self._parse_automation(meta.get("自动化", ""), test_types)
        acceptance = self._parse_gherkin("\n".join(sections.get("acceptance criteria", [])))
        business_rules = self._parse_bullets(sections.get("业务规则", []))
        test_data = self._parse_key_values(sections.get("测试数据", []))
        dod = self._parse_bullets(sections.get("definition of done", []))
        role = self._parse_phrase(body, "As a")
        goal = self._parse_phrase(body, "I want")
        benefit = self._parse_phrase(body, "So that")

        description_parts = [p for p in (goal, benefit) if p]
        if business_rules:
            description_parts.append("业务规则：" + "；".join(business_rules))
        description = "\n".join(description_parts)

        acceptance_criteria = [
            item["name"] + "：" + "；".join(item["then"]) if item["then"] else item["name"]
            for item in acceptance
        ]
        if not acceptance_criteria and dod:
            acceptance_criteria = list(dod)

        return {
            "title": story_title or title,
            "story_key": story_key,
            "epic": epic,
            "sprint": sprint,
            "module": meta.get("组件", ""),
            "test_types": test_types,
            "type": primary,
            "priority": priority,
            "story_points": self._to_int(meta.get("storypoints", "")),
            "role": role,
            "goal": goal,
            "benefit": benefit,
            "business_rules": business_rules,
            "test_data": test_data,
            "acceptance": acceptance,
            "definition_of_done": dod,
            "automation": automation,
            "api_ref": self._clean_ref(meta.get("关联接口", "")),
            "tags": self._split_list(meta.get("标签", "")),
            "env": env,
            "description": description,
            "acceptance_criteria": acceptance_criteria,
            "raw_text": f"{title}\n{body}".strip(),
        }

    # --------------------------------------------------------
    @staticmethod
    def _split_key(title: str) -> tuple[str, str]:
        match = _STORY_KEY_RE.match(title or "")
        if match:
            return match.group(1), match.group(2).strip()
        return "", (title or "").strip()

    @staticmethod
    def _parse_meta(body: str) -> dict:
        meta = {}
        for line in body.split("\n"):
            match = _META_RE.match(line)
            if match:
                meta[match.group(1).lower().replace(" ", "")] = match.group(2).strip()
        return meta

    def _split_bold_sections(self, body: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        current: str | None = None
        for line in body.split("\n"):
            match = _BOLD_SECTION_RE.match(line)
            if match:
                current = match.group(1).strip().lower()
                sections.setdefault(current, [])
                continue
            if current:
                sections[current].append(line)
        return sections

    @staticmethod
    def _parse_phrase(body: str, label: str) -> str:
        pattern = re.compile(rf"\*\*{re.escape(label)}\*\*\s*(.+)", re.IGNORECASE)
        for line in body.split("\n"):
            match = pattern.search(line)
            if match:
                return match.group(1).strip()
        return ""

    @staticmethod
    def _parse_bullets(lines: list[str]) -> list[str]:
        items = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            item = re.sub(r"^[-*+]\s*(\[[ xX]\]\s*)?", "", stripped).strip()
            if item:
                items.append(item)
        return items

    @staticmethod
    def _parse_key_values(lines: list[str]) -> dict:
        data = {}
        for line in lines:
            stripped = line.strip()
            match = re.match(r"^[-*+]?\s*(.+?)\s*[:：]\s*(.+?)\s*$", stripped)
            if match:
                data[match.group(1).strip()] = match.group(2).strip()
        return data

    def _parse_gherkin(self, block: str) -> list[dict]:
        if not block.strip():
            return []
        scenarios: list[dict] = []
        current: dict | None = None
        last = "given"
        for raw in block.split("\n"):
            line = raw.strip().lstrip(">").strip()
            if not line or line.startswith("```"):
                continue
            scenario_match = _SCENARIO_RE.match(line)
            if scenario_match:
                current = {
                    "name": scenario_match.group(1).strip(),
                    "given": [], "when": [], "then": [], "steps": [],
                }
                scenarios.append(current)
                last = "given"
                continue
            step_match = _STEP_RE.match(line)
            if step_match and current is not None:
                keyword = step_match.group(1).lower()
                text = step_match.group(2).strip()
                kind = self._keyword_kind(keyword, last)
                last = kind
                current[kind].append(text)
                current["steps"].append({"keyword": kind, "text": text})
        return [s for s in scenarios if s["name"] or s["steps"]]

    @staticmethod
    def _keyword_kind(keyword: str, last: str) -> str:
        mapping = {
            "given": "given", "when": "when", "then": "then",
            "and": last, "but": last,
            "假如": "given", "当": "when", "那么": "then", "并且": last, "而且": last,
        }
        return mapping.get(keyword, last)

    def _parse_types(self, value: str) -> list[str]:
        types = []
        for token in self._split_list(value):
            normalized = _TYPE_MAP.get(token.lower())
            if normalized and normalized not in types:
                types.append(normalized)
        return types or ["functional"]

    @staticmethod
    def _split_list(value: str) -> list[str]:
        return [t.strip() for t in re.split(r"[,，、/|]+", value or "") if t.strip()]

    def _parse_automation(self, value: str, test_types: list[str]) -> dict:
        automation = {
            "manual": True,
            "ui": "ui" in test_types,
            "api": "api" in test_types,
        }
        for token in re.split(r"[,，、;；]+", value or ""):
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                key, _, raw = token.partition("=")
            elif "：" in token:
                key, _, raw = token.partition("：")
            else:
                continue
            key = key.strip().lower()
            raw = raw.strip().lower()
            if key not in automation:
                continue
            automation[key] = raw in _TRUE_VALUES
        return automation

    @staticmethod
    def _clean_ref(value: str) -> str:
        cleaned = (value or "").strip()
        return "" if cleaned.lower() in {"无", "none", "n/a", "-", "—"} else cleaned

    @staticmethod
    def _to_int(value) -> int | None:
        try:
            return int(str(value).strip())
        except (ValueError, TypeError):
            return None
