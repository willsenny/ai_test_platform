"""
Django 设置（沿用 WHartTest 结构，零改造复用）

WHartTest 技术栈: Django 5.2 + DRF + Vue 前端
本项目在其基础上扩充 RAG / Agent / MCP / SelfHeal 模块。
"""
from pathlib import Path
from urllib.parse import urlparse
import os

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PLATFORM_DIR = Path(__file__).resolve().parent.parent

# 加载 platform/.env（Phase C 依赖 python-dotenv）
try:
    from dotenv import load_dotenv

    load_dotenv(PLATFORM_DIR / ".env")
except ImportError:
    pass

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",  # API 文档
    # 本项目 (沿用 WHartTest 模块结构)
    "apps.core",         # 项目管理 (复用)
    "apps.testcases",    # 用例库 (复用 + 扩充)
    "apps.rag",          # RAG 知识库 (复用 WHartTest Qdrant + Reranker)
    "apps.agent",        # LangGraph 编排 (新增)
    "apps.mcp",          # MCP Client (新增, 支持 stdio + SSE)
    "apps.executor",     # 执行器 (复用 WHartTest Actuator)
    "apps.selfheal",     # 自愈引擎 (新增, 核心差异化)
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"

# ============================================================
# Media（执行报告输出：media/reports/run_{id}.html）
# ============================================================
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ============================================================
# 数据库（沿用 WHartTest PostgreSQL 配置）
# ============================================================
def _db_from_env() -> dict:
    """支持 DATABASE_URL 或 DB_* 两种配置方式。"""
    url = os.getenv("DATABASE_URL", "")
    if url:
        parsed = urlparse(url)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": (parsed.path or "/ai_test").lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
        }
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "ai_test"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }


DATABASES = {"default": _db_from_env()}

# ============================================================
# DRF
# ============================================================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# ============================================================
# CORS (开发期允许前端跨域)
# ============================================================
CORS_ALLOW_ALL_ORIGINS = DEBUG

# ============================================================
# Agent 配置
# ============================================================
AGENT_CONFIG = {
    # Flash-Only：唯一模型，通过 reasoning 档位区分思考深度
    "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
    "reasoning_levels": ["low", "high"],
    # 离线兜底（可选）
    "local_fallback": {
        "model": os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b"),
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
    },
    "retry_budget": int(os.getenv("RETRY_BUDGET", "3")),
    "daily_budget_usd": float(os.getenv("DAILY_BUDGET", "10.0")),
}

# ============================================================
# RAG 配置（沿用 WHartTest: Qdrant + Reranker + Xinference）
# ============================================================
RAG_CONFIG = {
    # Phase G：RAG 总开关；置 0 时检索返回空、写入跳过（系统降级）
    "enabled": os.getenv("RAG_ENABLED", "1").strip().lower()
    not in ("0", "false", "no", "off"),
    "qdrant_url": os.getenv("QDRANT_URL", "http://localhost:6333"),
    "qdrant_api_key": os.getenv("QDRANT_API_KEY"),
    # auto: 先试远端 Qdrant，不可达则回退本地嵌入式 store（无 Docker 时可用）
    "qdrant_mode": os.getenv("QDRANT_MODE", "auto"),
    "qdrant_local_path": os.getenv(
        "QDRANT_LOCAL_PATH", str(PLATFORM_DIR / ".qdrant_local")
    ),
    # Phase G collections
    "collections": {
        "testcases": "testcases",
        "step_results": "step_results",
        "heal_logs": "heal_logs",
    },
    # 仅用 score 阈值过滤（不接 reranker）
    "score_threshold": float(os.getenv("RAG_SCORE_THRESHOLD", "0.0")),
    # 开发用 FakeEmbedder(dim=8)；生产 RAG_EMBEDDER=bge + Embedding HTTP 服务
    "embedder": os.getenv("RAG_EMBEDDER", "fake"),
    "fake_dim": int(os.getenv("RAG_FAKE_DIM", "8")),
    # 兼容旧知识库 collection
    "collection": "test_knowledge",
    "embedding": {
        "base_url": os.getenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1"),
        "model": os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
        "dimension": int(os.getenv("EMBEDDING_DIM", "1024")),
    },
    "reranker": {
        "base_url": os.getenv("RERANK_BASE_URL", "http://localhost:8001"),
        "model": os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
    },
}

# ============================================================
# MCP 配置
# ============================================================
MCP_CONFIG_FILE = os.getenv(
    "MCP_CONFIG",
    str(BASE_DIR / "apps" / "mcp" / "config.json"),
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
