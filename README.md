# AI 测试管理平台 - 骨架代码

基于 **WHartTest (MIT) + OpenCode + LangGraph + Qdrant + Playwright MCP** 的 AI 测试工作流平台骨架。

## 模型策略（DeepSeek Flash-Only）

| 档位 | 模型 | 用途 | 占比 |
|---|---|---|---|
| `low` | DeepSeek V4.1 Flash | 用例/步骤/断言生成、批量回归、日志摘要 | ~90% |
| `high` | DeepSeek V4.1 Flash (reasoning) | 需求理解、多文件重构、自愈根因 | ~10% |
| 兜底 | 本地 Ollama (`qwen2.5-coder`) | 离线/断网降级 | 极少 |

> 2026-09 起 Sonnet 弃用（翻墙+合规风险），V4 Pro 已并入 V4.1 Flash（按 Flash 计费）。
> 唯一模型 + `reasoning_effort` 区分思考深度，~$0.14/M input、~$0.28/M output。
> 路由映射见 `platform/apps/agent/router.py` 的 `TASK_ROUTING`。

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
│   │   │   ├── router.py       # Flash-Only 路由 (reasoning low/high)
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
cp ../.env.example .env
# 填入 DEEPSEEK_API_KEY

# 4. 初始化 RAG 知识库（scripts 位于仓库根目录）
uv run python ../scripts/init_qdrant.py

# 5. 迁移数据库并启动平台
uv run python manage.py migrate
uv run python manage.py runserver

# 6. 在 OpenCode 中开发
cd ../opencode && opencode .
```

## 核心工作流

```
需求文档 → RAG 检索 → LangGraph 编排 → DeepSeek Flash 生成用例/代码
    → Playwright MCP 执行 → 失败? → 自愈闭环 → 通过 → 入库
```

详见各模块 README。
