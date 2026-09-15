# AI 测试管理平台

基于 **WHartTest (MIT) + OpenCode + LangGraph + Qdrant + MCP + Playwright** 的 AI 测试工作流平台：
从自然语言需求生成结构化用例 → 真浏览器执行 → 失败自动自愈 → RAG 复用历史经验。

> 每个代码文件的功能说明见 [`docs/CODE_FILES.md`](docs/CODE_FILES.md)（人工修改/审核用）。
> 各阶段执行计划与验证记录见 [`plan.md`](plan.md)。

## 实现状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase C | 最小闭环（Fake MCP：Django → LangGraph → MCP stdio → PostgreSQL） | ✅ |
| Phase D | 真 Playwright MCP 执行（生成即执行） | ✅ |
| Phase E | 执行结果模型（TestRun/TestStepResult）+ JSON/HTML 报告 | ✅ |
| Phase F | 自愈五段闭环（规则驱动：分析 → 修复 → 重跑 → 沉淀） | ✅ |
| Phase G | RAG 检索增强（Qdrant + embedding，planner/analyzer/fixer 接入） | ✅ |
| Phase H | 成本 / 日志 / 人类审批 / CI | ⬜ |

## 模型策略（DeepSeek Flash-Only）

| 档位 | 模型 | 用途 | 占比 |
|---|---|---|---|
| `low` | DeepSeek V4.1 Flash | 用例/步骤/断言生成、批量回归、日志摘要 | ~90% |
| `high` | DeepSeek V4.1 Flash (reasoning) | 需求理解、多文件重构、自愈根因 | ~10% |
| 兜底 | 本地 Ollama (`qwen2.5-coder`) | 离线/断网降级 | 极少 |

> 唯一模型 + `reasoning_effort` 区分思考深度。路由映射见 `platform/apps/agent/router.py` 的 `TASK_ROUTING`。

## 目录结构

```
ai_test_platform/
├── README.md
├── QUICKSTART.md
├── plan.md                     # 各阶段计划与验证记录
├── docs/CODE_FILES.md          # 逐文件功能说明（审核用）
├── docker-compose.yml          # Qdrant + PostgreSQL + Redis（有 Docker 时使用）
├── .env.example
├── opencode/                   # OpenCode 配置 + Skills
│   ├── config.yaml
│   └── skills/{test-generator,self-heal}/
├── platform/                   # Django Monorepo（WHartTest 底座扩充）
│   ├── manage.py
│   ├── pyproject.toml
│   ├── config/                 # settings / urls / asgi / wsgi
│   └── apps/
│       ├── core/               # 项目管理（复用）
│       ├── testcases/          # 用例库（复用 + 扩充）
│       ├── rag/                # RAG：embedder / retriever / indexer / signals + service（旧知识库）
│       ├── agent/              # LangGraph 编排 + Flash-Only 路由
│       │   ├── graph.py        # 完整图 + Phase C–G demo 闭环
│       │   ├── nodes.py        # legacy 完整图节点
│       │   ├── router.py       # reasoning low/high 路由
│       │   ├── llm.py          # litellm/httpx 调用适配
│       │   ├── state.py
│       │   └── management/commands/run_agent_demo.py
│       ├── mcp/                # MCP Client（stdio + SSE）
│       ├── executor/           # 执行器 + TestRun/TestStepResult + 报告
│       └── selfheal/           # 自愈：analyzer / fixer / learner / engine
├── mcp_servers/                # MCP Server（stdio）
│   ├── echo_server.py          # 确定性假数据生成（few-shot 复用）
│   ├── playwright_server.py    # 真浏览器执行
│   ├── api_server.py / db_server.py / git_server.py
│   └── fixtures/login.html     # 本地登录示例页
├── tests/                      # test_e2e.py + test_rag_phase_g.py
└── scripts/                    # init_qdrant.py / seed_demo.py / generate_diagrams.py
```

## 快速开始

```bash
# 1. 基础设施
#    有 Docker：
docker-compose up -d
#    无 Docker：Qdrant 无需启动，默认 QDRANT_MODE=auto 会回退本地嵌入式索引（platform/.qdrant_local）
#    仍需本机 PostgreSQL（或用 docker-compose 的 postgres）。

# 2. 安装依赖（示例：Python venv）
cd platform
python3 -m venv .venv && . .venv/bin/activate
pip install django djangorestframework djangorestframework-simplejwt django-cors-headers \
  drf-spectacular langgraph langchain-core pydantic litellm httpx mcp qdrant-client \
  psycopg[binary] python-dotenv pytest pytest-asyncio pytest-json-report playwright

# 3. 配置环境变量
cp ../.env.example .env    # 填入 DEEPSEEK_API_KEY、DATABASE_URL

# 4. 迁移数据库
python manage.py migrate

# 5a. 启动平台
python manage.py runserver          # API 文档 http://localhost:8000/api/docs/

# 5b. 或跑 Phase C–G 演示闭环（生成 → 执行 → 自愈）
python manage.py run_agent_demo --goal "用户登录" --count 3 --execute --self-heal
```

## 核心工作流

```
需求文档 → RAG 检索历史用例 → LangGraph 编排 → DeepSeek Flash 生成用例/代码
    → Playwright MCP 执行 → 失败? → 自愈（检索历史修复经验）→ 通过 → 入库
```

### Phase G RAG 接入点

- **planner**：生成前 `retrieve_similar_cases(goal)` 取 top-3 历史用例作为 few-shot，
  `echo_server.fake_generate_test` 复用历史 selector 模式；日志打印 `[retrieved N similar cases]`。
- **analyzer**：自愈失败时 `retrieve_similar_failures(selector, error)` 找历史同类失败。
- **fixer**：`retrieve_heal_experience(pattern)` 找历史成功修复策略并提示/兜底。
- **写入**：`TestCase` / 失败 `TestStepResult` / `SelfHealLog` 保存时向量化到
  Qdrant collection `testcases` / `step_results` / `heal_logs`。
- **Embedder**：`RAG_EMBEDDER=fake`（开发，dim=8）或 `bge`（生产，bge-m3 / text2vec-large-chinese）。
- **降级**：`RAG_ENABLED=0` 或 Qdrant 不可达时检索返回空、写入跳过，主流程不阻断。

## 测试

```bash
pytest -q                     # 30 passed
cd platform && python manage.py check
```
