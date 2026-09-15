"""
Django 设置（沿用 WHartTest 结构，零改造复用）

WHartTest 技术栈: Django 5.2 + DRF + Vue 前端
本项目在其基础上扩充 RAG / Agent / MCP / SelfHeal 模块。
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent.parent

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
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "ai_test"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

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
    "model_tiers": {
        "l1": os.getenv("MODEL_L1", "deepseek-chat"),
        "l2": os.getenv("MODEL_L2", "deepseek-reasoner"),
        "l3": os.getenv("MODEL_L3", "claude-sonnet-4-6"),
    },
    "retry_budget": int(os.getenv("RETRY_BUDGET", "3")),
    "daily_budget_usd": float(os.getenv("DAILY_BUDGET", "10.0")),
}

# ============================================================
# RAG 配置（沿用 WHartTest: Qdrant + Reranker + Xinference）
# ============================================================
RAG_CONFIG = {
    "qdrant_url": os.getenv("QDRANT_URL", "http://localhost:6333"),
    "qdrant_api_key": os.getenv("QDRANT_API_KEY"),
    "collection": "test_knowledge",
    "embedding": {
        "base_url": os.getenv("EMBEDDING_BASE_URL", "http://localhost:8000/v1"),
        "model": os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5"),
        "dimension": 1024,
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
