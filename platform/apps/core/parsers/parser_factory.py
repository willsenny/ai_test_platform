"""解析器工厂：按文件类型（可结合文本特征）返回解析器实例。"""
from .base import BaseParser
from .markdown_parser import MarkdownParser
from .story_parser import StoryParser, looks_like_story

_PARSERS: tuple[type[BaseParser], ...] = (MarkdownParser, StoryParser)

# MIME / 别名 → 规范 file_type
_ALIASES = {
    "text/markdown": "md",
    "text/x-markdown": "md",
    "text/plain": "txt",
    "application/octet-stream": "",
}


def _normalize(file_type: str) -> str:
    value = (file_type or "").strip().lower()
    if value in _ALIASES:
        return _ALIASES[value]
    if "/" in value:
        return value.split("/")[-1]
    if "." in value:
        value = value.rsplit(".", 1)[-1]
    return value.lstrip(".")


def supported_file_types() -> list[str]:
    types: set[str] = set()
    for parser_cls in _PARSERS:
        types.update(getattr(parser_cls, "FILETYPES", {parser_cls.file_type}))
    return sorted(t for t in types if t)


def get_parser(file_type: str, sample_text: str | None = None) -> BaseParser:
    """按文件类型返回解析器实例；给出文本时优先匹配内容特征（Jira Story）。

    不支持的类型抛 ValueError。
    """
    normalized = _normalize(file_type)
    supported = any(parser_cls.supports(normalized) for parser_cls in _PARSERS)
    if sample_text and supported and looks_like_story(sample_text):
        return StoryParser()
    for parser_cls in _PARSERS:
        if parser_cls.supports(normalized):
            return parser_cls()
    raise ValueError(
        f"Unsupported file type: {file_type!r}. "
        f"Supported: {', '.join(supported_file_types())}"
    )
