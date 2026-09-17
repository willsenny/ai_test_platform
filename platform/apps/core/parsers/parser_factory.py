"""解析器工厂：按文件类型返回对应解析器实例。"""
from .base import BaseParser
from .markdown_parser import MarkdownParser

_PARSERS: tuple[type[BaseParser], ...] = (MarkdownParser,)

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


def get_parser(file_type: str) -> BaseParser:
    """按文件类型返回解析器实例，不支持时抛 ValueError。"""
    normalized = _normalize(file_type)
    for parser_cls in _PARSERS:
        if parser_cls.supports(normalized):
            return parser_cls()
    raise ValueError(
        f"Unsupported file type: {file_type!r}. "
        f"Supported: {', '.join(supported_file_types())}"
    )
