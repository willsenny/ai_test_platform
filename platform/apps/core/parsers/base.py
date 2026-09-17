"""
解析器抽象基类。

parse() 输出统一结构（list[dict]）：
    {
        "title": str,
        "description": str,
        "type": "ui" | "api",
        "priority": "P0" | "P1" | "P2",
        "raw_text": str,
        "acceptance_criteria": list[str],
        "tags": list[str],
        "spec": dict,   # 可选：显式 UI/API 规格（来自 ```json 代码块）
    }
"""
from abc import ABC, abstractmethod


class BaseParser(ABC):
    """需求文档解析器接口。"""

    #: 该解析器对应的文件类型标识（如 "md"）
    file_type: str = ""

    @abstractmethod
    def parse(self, text: str) -> list[dict]:
        """把文档文本解析为结构化场景列表。"""
        raise NotImplementedError

    @classmethod
    def supports(cls, file_type: str) -> bool:
        return (file_type or "").strip().lower().lstrip(".") == cls.file_type
