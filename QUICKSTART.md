# 快速开始

## 1. 启动基础设施

```bash
docker-compose up -d   # Qdrant + PostgreSQL + Redis
```

## 2. 安装依赖

```bash
cd platform
uv sync   # 或 pip install -e .
```

## 3. 配置环境变量

```bash
cp ../.env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

## 4. 初始化

```bash
python ../scripts/init_qdrant.py
```

输出:
```
🚀 初始化 AI 测试管理平台...

1. 初始化 Qdrant...
✅ Qdrant collection 'test_knowledge' ready

2. 导入示例文档...
  ✅ prd/user_login.md
  ✅ api/auth.yaml
  ✅ bugs/auth.txt

🎉 已导入 3 份示例文档

3. 验证模型路由...
  ✅ generate_testcase         → low    (deepseek-flash)
  ✅ generate_steps            → low    (deepseek-flash)
  ✅ refactor_code             → high   (deepseek-flash)
  ✅ self_heal_repair          → high   (deepseek-flash)

✅ 初始化完成！
```

## 5. 启动平台

```bash
python manage.py migrate   # 初始化数据库（Project / TestCase 表）
python manage.py runserver
# API 文档: http://localhost:8000/api/docs/
```

## 6. 在 OpenCode 中开发

```bash
cd opencode
opencode .
```

OpenCode 会自动加载 `config.yaml` 中的模型路由和 Skills。

---

## 核心 API

### 生成测试用例

```bash
curl -X POST http://localhost:8000/api/v1/agent/generate \
  -H "Content-Type: application/json" \
  -d '{
    "requirement": "用户登录：手机号+验证码",
    "project_id": "demo",
    "retry_budget": 3
  }'
```

### 自愈

```bash
curl -X POST http://localhost:8000/api/v1/agent/heal \
  -H "Content-Type: application/json" \
  -d '{
    "test_id": "login_001",
    "error_message": "TimeoutError: waiting for #submit-btn",
    "locator": "#submit-btn",
    "page_url": "https://example.com/login"
  }'
```

### RAG 检索

```bash
curl -X POST http://localhost:8000/api/v1/rag/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "验证码 过期", "project_id": "demo", "top_k": 5}'
```

### 成本报告

```bash
curl http://localhost:8000/api/v1/agent/cost
```

---

## 跑测试

```bash
pytest tests/ -v
```

---

## 模型成本速查（Flash-Only）

| 档位 | 模型 | 价格 (每 M tokens) | 占比 |
|---|---|---|---|
| low | DeepSeek V4.1 Flash | $0.14 / $0.28 (cached $0.0028) | ~90% |
| high | DeepSeek V4.1 Flash (reasoning) | 同上（按 Flash 计费） | ~10% |
| 兜底 | 本地 Ollama | 免费（自建算力） | 极少 |

**中型冲刺 (100 需求 × 8 用例) 成本:**
- 纯 Sonnet: ~$50
- 旧三层路由: ~$8
- **Flash-Only: ~$2** ← 你在这里

---

## 项目结构

```
ai_test_platform/
├── README.md
├── QUICKSTART.md          ← 你在这里
├── .env.example
├── .gitignore
├── docker-compose.yml
│
├── opencode/              # OpenCode 配置 + Skills
│   ├── config.yaml        # 模型路由 (Flash-Only, reasoning low/high)
│   └── skills/
│       ├── test-generator/
│       └── self-heal/
│
├── platform/              # Django Monorepo (WHartTest 底座)
│   ├── pyproject.toml
│   ├── config/            # Django settings/urls
│   ├── apps/
│   │   ├── core/          # 项目管理 (复用 WHartTest)
│   │   ├── testcases/     # 用例库 (复用+扩充)
│   │   ├── rag/           # Qdrant + Reranker
│   │   ├── agent/         # LangGraph 编排 + 模型路由
│   │   ├── mcp/           # MCP Client (stdio + SSE)
│   │   ├── executor/      # 执行器 (Playwright)
│   │   └── selfheal/      # 自愈引擎 ⭐ 核心差异化
│   └── templates/
│
├── mcp_servers/           # MCP Server 实现
│   ├── playwright_server.py
│   ├── api_server.py
│   ├── db_server.py
│   └── git_server.py
│
├── tests/                 # 集成测试
│   └── test_e2e.py
│
├── scripts/
│   ├── init_qdrant.py
│   ├── seed_demo.py
│   └── generate_diagrams.py
│
├── architecture.png       # 架构图
├── cost_comparison.png    # 成本对比图
└── self_heal_flow.png     # 自愈流程图
```
