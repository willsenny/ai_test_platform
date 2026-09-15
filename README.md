# AI 测试管理平台 - 骨架代码

基于 **WHartTest (MIT) + OpenCode + LangGraph + Qdrant + Playwright MCP** 的 AI 测试工作流平台骨架。

## 模型策略（DeepSeek 为主）

| 层级 | 模型 | 用途 | 占比 |
|---|---|---|---|
| L1 | DeepSeek V4 Flash | 用例/步骤/断言生成、批量回归 | 70% |
| L2 | DeepSeek V4 Pro | Django 平台开发、复杂编排、代码评审 | 25% |
| L3 | Claude Sonnet 4.6 | 自愈修复、疑难根因（兜底） | 5% |

> SWE-bench Verified: Sonnet 79.6% vs DeepSeek Flash 79.0%，仅差 0.6 个点。
> 代码生成类任务用 Flash 几乎无损，便宜 21-53 倍。Pro 用于多文件重构更稳。

## 目录结构

```
ai_test_platform/
├── README.md
├── docker-compose.yml          # Qdrant + PostgreSQL + Redis
├── .env.example
├── opencode/
│   ├── config.yaml             # OpenCode 配置（DeepSeek 为主）
│   └── skills/                 # 自定义 Skill
│       ├── test-generator/
│       ├── self-heal/
│       └── api-tester/
├── platform/                   # Django Monorepo (基于 WHartTest 扩充)
│   ├── manage.py
│   ├── pyproject.toml
│   ├── apps/
│   │   ├── core/               # 项目管理（复用 WHartTest）
│   │   ├── testcases/          # 用例库（复用 + 扩充）
│   │   ├── rag/                # Qdrant + Reranker
│   │   ├── agent/              # LangGraph 编排
│   │   │   ├── graph.py
│   │   │   ├── nodes.py
│   │   │   ├── router.py       # L1/L2/L3 模型路由
│   │   │   └── state.py
│   │   ├── mcp/                # MCP Client (stdio + SSE)
│   │   ├── executor/           # Playwright 执行器
│   │   └── selfheal/           # 自愈五段闭环
│   └── config/
├── mcp_servers/                # MCP Server 实现
│   ├── playwright_server.py    # Playwright MCP (stdio)
│   ├── api_server.py           # API 测试 MCP
│   └── db_server.py            # 数据库断言 MCP
├── tests/                      # 平台自身测试
└── scripts/
    ├── init_qdrant.py
    └── seed_demo.py
```

## 快速开始

```bash
# 1. 启动基础设施
docker-compose up -d

# 2. 安装依赖
cd platform && uv sync

# 3. 配置环境变量
cp .env.example .env
# 填入 DEEPSEEK_API_KEY

# 4. 初始化 RAG 知识库
uv run python scripts/init_qdrant.py

# 5. 启动平台
uv run python manage.py runserver

# 6. 在 OpenCode 中开发
cd ../opencode && opencode .
```

## 核心工作流

```
需求文档 → RAG 检索 → LangGraph 编排 → DeepSeek 生成用例/代码
    → Playwright MCP 执行 → 失败? → 自愈闭环 → 通过 → 入库
```

详见各模块 README。
