"""core 业务服务包。"""
from .doc_service import parse_doc
from .generation_service import generate_from_doc

__all__ = ["parse_doc", "generate_from_doc"]
