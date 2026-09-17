"""
Markdown 需求解析器。

按标题层级提取测试场景：
- `##` 标题作为场景边界（无 `##` 时回退到 `#`）
- 场景正文中的 ```json 代码块作为显式规格（UI steps / API request）
- 含 HTTP 动词 + 路径 / ```http 块 / API 关键词 → type = "api"，否则 "ui"
- 识别 优先级 / 标签 / 验收标准
"""
import json
import re

from .base import BaseParser

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_HTTP_FENCE_RE = re.compile(r"```http\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

_PRIORITY_RE = re.compile(r"\bP([0-2])\b", re.IGNORECASE)
_PRIORITY_LABEL_RE = re.compile(r"(?:优先级|priority)\s*[:：]\s*(P[0-2]|高|中|低)", re.IGNORECASE)
_TAGS_RE = re.compile(r"(?:标签|tags?)\s*[:：]\s*(.+)", re.IGNORECASE)
_ACCEPT_HEADING_RE = re.compile(r"(验收|acceptance|预期结果|expected result)", re.IGNORECASE)

_HTTP_VERBS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
_API_TEXT_RE = re.compile(
    r"\b(" + "|".join(_HTTP_VERBS) + r")\s+(https?://\S+|/[^\s`、,，]*)"
)
_API_PATH_RE = re.compile(
    r"(?:接口地址|接口|地址|路径|url|endpoint)\s*[:：]\s*(\S+)", re.IGNORECASE
)
_API_KEYWORDS = ("接口", "api", "请求", "响应", "status code")

_PRIORITY_MAP = {"高": "P0", "中": "P1", "低": "P2"}


class MarkdownParser(BaseParser):
    file_type = "md"
    FILETYPES = {"md", "markdown", "txt", "text"}

    def __init__(self, scenario_level: int = 2):
        self.scenario_level = scenario_level

    @classmethod
    def supports(cls, file_type: str) -> bool:
        return (file_type or "").strip().lower().lstrip(".") in cls.FILETYPES

    # --------------------------------------------------------
    def parse(self, text: str) -> list[dict]:
        sections = self._split_sections(text)
        named = [s for s in sections if s[0] != "未命名场景"]
        if named:
            sections = named
        scenarios = [self._build_scenario(title, body) for title, body in sections]
        return [s for s in scenarios if s]

    # --------------------------------------------------------
    def _split_sections(self, text: str) -> list[tuple[str, str]]:
        """返回 [(title, body), ...]。"""
        lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        sections: list[tuple[str, list[str]]] = []
        in_code = False
        for line in lines:
            if line.strip().startswith("```"):
                in_code = not in_code
            match = None if in_code else _HEADING_RE.match(line)
            if match:
                level = len(match.group(1))
                if 1 < level <= self.scenario_level + 4 and level <= self.scenario_level:
                    sections.append((match.group(2).strip(), []))
                    continue
            if not sections:
                if line.strip():
                    sections.append(("未命名场景", []))
                else:
                    continue
            sections[-1][1].append(line)

        # 没有任何场景级标题时，回退用一级标题
        if not any(t != "未命名场景" for t, _ in sections):
            sections = self._split_by_level(lines, 1)

        return [(title, "\n".join(body).strip()) for title, body in sections]

    def _split_by_level(self, lines: list[str], level: int) -> list[tuple[str, list[str]]]:
        sections: list[tuple[str, list[str]]] = []
        in_code = False
        for line in lines:
            if line.strip().startswith("```"):
                in_code = not in_code
            match = None if in_code else _HEADING_RE.match(line)
            if match and len(match.group(1)) == level:
                sections.append((match.group(2).strip(), []))
                continue
            if sections:
                sections[-1][1].append(line)
        return sections

    # --------------------------------------------------------
    def _build_scenario(self, title: str, body: str) -> dict | None:
        if not title and not body:
            return None
        spec = self._extract_spec(body)
        prose = self._strip_code_fences(body)

        scenario_type = self._infer_type(prose, spec, body)
        priority = self._infer_priority(title, body)
        tags = self._infer_tags(body)
        if scenario_type not in tags:
            tags.append(scenario_type)
        acceptance = self._extract_acceptance(body)

        scenario = {
            "title": title or "未命名场景",
            "description": prose.strip(),
            "type": scenario_type,
            "priority": priority,
            "raw_text": f"{title}\n{body}".strip(),
            "acceptance_criteria": acceptance,
            "tags": tags,
        }
        if spec:
            scenario["spec"] = spec
            if scenario_type == "api":
                scenario["api"] = self._build_api_spec(prose, spec)
        return scenario

    # --------------------------------------------------------
    @staticmethod
    def _extract_spec(body: str) -> dict | None:
        for block in _JSON_FENCE_RE.findall(body or ""):
            try:
                data = json.loads(block.strip())
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and (
                data.get("type") or data.get("steps") or data.get("request")
            ):
                return data
        return None

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        return re.sub(r"```.*?```", "", text or "", flags=re.DOTALL).strip()

    def _infer_type(self, prose: str, spec: dict | None, raw_body: str = "") -> str:
        if spec and spec.get("type") in ("ui", "api"):
            return spec["type"]
        if _HTTP_FENCE_RE.search(raw_body or ""):
            return "api"
        if _API_TEXT_RE.search(prose or ""):
            return "api"
        lowered = (prose or "").lower()
        if any(k in lowered for k in _API_KEYWORDS):
            return "api"
        return "ui"

    def _infer_priority(self, title: str, body: str) -> str:
        label = _PRIORITY_LABEL_RE.search(f"{title}\n{body}")
        if label:
            value = label.group(1).upper()
            return _PRIORITY_MAP.get(label.group(1), value if value.startswith("P") else "P1")
        match = _PRIORITY_RE.search(title) or _PRIORITY_RE.search(body)
        if match:
            return f"P{match.group(1)}"
        return "P1"

    def _infer_tags(self, body: str) -> list[str]:
        match = _TAGS_RE.search(body or "")
        if not match:
            return []
        return [t.strip() for t in re.split(r"[,，、\s]+", match.group(1)) if t.strip()]

    def _extract_acceptance(self, body: str) -> list[str]:
        lines = (body or "").split("\n")
        items: list[str] = []
        in_accept = False
        for line in lines:
            heading = _HEADING_RE.match(line)
            if heading:
                in_accept = bool(_ACCEPT_HEADING_RE.search(heading.group(2)))
                continue
            if not in_accept:
                continue
            stripped = line.strip()
            item = re.sub(r"^[-*+]\s*(\[\s?[ xX]\s?\]\s*)?", "", stripped).strip()
            if item:
                items.append(item)
        return items

    def _build_api_spec(self, prose: str, spec: dict) -> dict:
        request = spec.get("request") if isinstance(spec.get("request"), dict) else {}
        method = str(request.get("method") or "").upper()
        path = request.get("path") or request.get("url") or ""

        if not method or not path:
            match = _API_TEXT_RE.search(prose or "")
            if match:
                method = method or match.group(1).upper()
                path = path or match.group(2)
        if not path:
            match = _API_PATH_RE.search(prose or "")
            if match:
                path = match.group(1)

        return {
            "method": method or "GET",
            "path": path,
            "headers": request.get("headers") or {},
            "body": request.get("body") or request.get("json") or {},
            "params": request.get("params") or {},
            "expected_status": int(
                request.get("expected_status")
                or spec.get("expected_status")
                or 200
            ),
            "assertions": spec.get("assertions")
            or [{"type": "status_equals", "expected": 200}],
        }
