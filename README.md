# AI 测试管理平台

基于 **WHartTest (MIT) + OpenCode + LangGraph + Qdrant + MCP + Playwright** 的 AI 测试工作流平台：
从自然语言需求生成结构化用例 → 真浏览器执行 → 失败自动自愈 → RAG 复用历史经验。

Phase I 打通产品化链路：**上传需求文档 → 自动解析场景 → 批量生成用例 → 自动执行 → 自动自愈**，全链路一条命令、无手动 flag。

Phase J（M1）在其上升级为**真实 LLM 驱动**：输入 Jira Sprint Story（Gherkin），AI 生成 **手动用例 / UI 自动化 / 接口自动化** 三类产物，执行+自愈后**归档并导出交付**（Excel / pytest 工程 / JSON），并提供 Web 审核与运行界面。

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
| Phase I | 产品化链路（需求文档 → 批量生成 → 执行 → 自愈 + Web 最小入口） | ✅ |
| Phase J | Jira Story → AI 生成 手动/UI/接口 用例 → 执行 → 自愈 → 归档导出（M1） | ✅ |
| Phase H | 成本 / 日志 / 人类审批 / CI | ⬜ |
| M2 | 内网站点探索生成 + 简单登录认证（真实站点替换本地 fixture） | ⬜ |
| M3 | 服务器 + CICD（Celery/SSE/定时回归/通知/权限） | ⬜ |

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
│       ├── core/               # 项目管理 + Phase I/J 产品化链路
│       │   ├── models.py       # Project / RequirementDoc / Scenario / TestGenerationBatch / ExportJob / LLMCall
│       │   ├── mock_api.py     # 离线 API 夹具（login 规则 + /v3/api-docs）
│       │   ├── parsers/        # markdown_parser / story_parser(Jira) / openapi_parser(Swagger) / parser_factory
│       │   ├── services/       # doc_service / generation_service / swagger_service / export_service
│       │   ├── views.py / urls.py   # DRF API + Web（项目/上传/文档/场景编辑/批次/运行/报告/导出）
│       │   └── management/commands/  # process_doc / export_cases
│       ├── testcases/          # 用例库（kind/test_type/manual_steps/expected_result/scenario FK）
│       ├── rag/                # RAG：embedder / retriever / indexer / signals + service（旧知识库）
│       ├── agent/              # LangGraph 编排 + Flash-Only 路由 + LLM 生成
│       │   ├── generation.py   # call_structured / generate_for_scenario / 去重 / 成本 / 页面快照
│       │   ├── schemas.py      # ManualCase / UICase / ApiCase（pydantic）
│       │   ├── prompts/        # 手动/UI/接口 提示词（Story+Gherkin+RAG+页面元素）
│       │   ├── graph.py        # demo 图 + 生成图 + 完整图；generator_node(LLM)
│       │   ├── nodes.py / router.py / llm.py / state.py
│       │   └── management/commands/  # run_agent_demo / llm_smoke
│       ├── mcp/                # MCP Client（stdio + SSE）
│       ├── executor/           # 执行器 + TestRun/TestStepResult + 报告（UI/API 分支 + 自动自愈 + 截图）
│       └── selfheal/           # analyzer / fixer(向量定位器+LLM+API) / learner / engine + heal_stats
├── templates/
│   ├── core/                   # Web 入口（Bootstrap 5）：projects/upload/doc_detail/scenario_edit/batch_detail
│   └── requirements/story_template.md   # Jira Story 需求模板
├── mcp_servers/                # MCP Server（stdio）
│   ├── echo_server.py / playwright_server.py / api_server.py / db_server.py / git_server.py
│   └── fixtures/login.html     # 本地登录示例页
├── tests/                      # test_phase1_pipeline / test_story_parser / test_openapi_parser / test_generation / test_export / test_heal_enhance / test_rag_injection ...
│   ├── fixtures/{sample_requirements,story_requirements}.md, fixtures/openapi_sample.json
│   └── ...
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
  psycopg[binary] python-dotenv pytest pytest-asyncio pytest-json-report playwright \
  jsonschema openpyxl

# 3. 配置环境变量
cp ../.env.example .env    # 填入 DEEPSEEK_API_KEY、DATABASE_URL

# 4. 迁移数据库
python manage.py migrate

# 5a. 启动平台
python manage.py runserver          # API 文档 http://localhost:8000/api/docs/

# 5b. 或跑 Phase C–G 演示闭环（生成 → 执行 → 自愈）
python manage.py run_agent_demo --goal "用户登录" --count 3 --execute --self-heal

# 5c. 或跑 Phase I/J 产品化链路（Jira Story → 生成 → 执行 → 自愈）
python manage.py process_doc <doc_id>
# Web 入口：python manage.py runserver → http://localhost:8000/

# 6. Phase J 辅助命令
python manage.py llm_smoke --structured        # 验证真实 LLM + 结构化输出
python manage.py export_cases <batch_id>       # 导出 xlsx + pytest 工程 + JSON
python manage.py heal_stats                    # 自愈成功率
```

## 核心工作流

```
需求文档 → RAG 检索历史用例 → LangGraph 编排 → DeepSeek Flash 生成用例/代码
    → Playwright MCP 执行 → 失败? → 自愈（检索历史修复经验）→ 通过 → 入库
```

### Phase G RAG 接入点

- **planner**：生成前 `retrieve_similar_cases(goal)` 取 top-3 历史用例 + `retrieve_knowledge` 取知识片段，
  作为 few-shot 注入 LLM prompt（Phase J 起生成走真实 LLM，不再使用 echo 兜底）。
- **analyzer**：自愈失败时 `retrieve_similar_failures(selector, error)` 找历史同类失败。
- **fixer**：`retrieve_heal_experience(pattern)` 找历史成功修复策略；`retrieve_locator` 查向量定位器库。
- **写入**：`TestCase` / 失败 `TestStepResult` / `SelfHealLog` 保存时向量化到
  Qdrant collection `testcases` / `step_results` / `heal_logs`。
- **Embedder**：`RAG_EMBEDDER=fake`（开发，dim=8）或 `bge`（生产，bge-m3 / text2vec-large-chinese）。
- **降级**：`RAG_ENABLED=0` 或 Qdrant 不可达时检索返回空、写入跳过，主流程不阻断。

## Phase I：需求文档 → 批量生成 → 执行 → 自愈

一条命令打通全链路，无手动 flag：

```bash
cd platform
python manage.py process_doc <doc_id>
```

```
RequirementDoc(md) → MarkdownParser 解析场景（ui/api 分类）
   → build_generation_graph（planner→generator→reporter）逐场景生成 TestCase
   → execute_cases(auto_heal=True) 自动执行 + 失败自动自愈
   → TestGenerationBatch 计数（total/generated/executed/healed）+ TestRun JSON/HTML 报告
```

### 新增文件

| 文件 | 说明 |
|---|---|
| `platform/apps/core/parsers/` | `base` / `markdown_parser`（标题层级→场景，HTTP/JSON→`type: api`）/ `parser_factory` |
| `platform/apps/core/services/doc_service.py` | `parse_doc`：读文件 → 解析 → 写回 `parsed_scenarios` / `status` |
| `platform/apps/core/services/generation_service.py` | `generate_from_doc`：生成 → 执行 → 自愈 → 回写批次计数 |
| `platform/apps/core/management/commands/process_doc.py` | 一键链路命令 |
| `platform/apps/core/mock_api.py` | 离线 API 夹具服务（无外部依赖即可跑通 API 场景） |
| `templates/core/` | Bootstrap 最小入口：项目列表 / 上传 / 批次进度 / 报告 |
| `tests/fixtures/sample_requirements.md` | 2 个 UI 场景 + 1 个 API 场景 |
| `tests/test_phase1_pipeline.py` | 解析器 / 工厂 / 图编译 / API 断言测试 |

### 修改文件

- `core/models.py`：`Project` 加 `base_url` / `api_base_url` / `swagger_url`；新增 `RequirementDoc`、`TestGenerationBatch`。
- `testcases/models.py`：加 `project` FK，原 `project_id` 字符字段改为 `project_key`（serializer 保留 `project_id` 别名兼容）。
- `agent/graph.py`：`generator_node` 按 `type` 分支（ui → Playwright steps；api → request+assertions 经 `api_server` MCP）；新增 `build_generation_graph` / `build_full_graph` / `run_full_workflow`。
- `agent/state.py`：新增 `scenario` / `case_type` / `project_ref_pk` / `api_base_url` / `source`。
- `executor/executor.py`：新增 API 执行分支 + `execute_cases(auto_heal=True)` 自动自愈。
- `mcp_servers/api_server.py`：新增 `send_request` 工具。
- `core/views.py` / `core/urls.py` / `config/urls.py`：Web 入口注册。
- `core/admin.py` / `testcases/admin.py` / `testcases/views.py` / `testcases/serializers.py` / `rag/indexer.py`：适配新模型与字段。

### Web 入口

启动 `python manage.py runserver` 后：

- `/` 项目列表（文档 + 批次）
- `/docs/upload/` 上传 Markdown 需求文档
- `/batches/<id>/` 批次进度（生成 / 执行 / 自愈计数 + 失败步骤）
- `/batches/<id>/report/` 执行报告

### 降级与离线

- Qdrant 离线 / `RAG_ENABLED=0`：检索返回空、写入跳过，链路不阻断。
- 未配置 `api_base_url` 时 `process_doc` 自动启动本地 API 夹具（`mock_api.py`），API 场景仍走 `api_server` MCP 真实请求。
- 不在本期范围：PDF/DOCX 解析、Swagger 拉取、Celery、用户权限、截图录像、Reranker、前端框架。

## Phase J：Jira Story → 三类用例 → 归档导出（M1）

输入 Jira Sprint Story（含 Gherkin 验收标准），AI 生成 **手动用例 / UI 自动化 / 接口自动化** 三类产物，
执行 + 失败自愈，并**归档导出交付**（Excel / pytest 工程 / JSON）；提供 Web 审核与运行界面。

### 需求模板

- 空模板：`templates/requirements/story_template.md`
- 真实样例：`tests/fixtures/story_requirements.md`
- 结构：`# Epic` → `> UI/API/Swagger` → `## Sprint` → `### Story: KEY-101`（类型/优先级/自动化/关联接口）
  + `As a / I want / So that` + 业务规则 + 测试数据 + ```gherkin 验收标准 + DoD。

### 一键链路

```bash
cd platform
python manage.py process_doc <doc_id>
```

```
Story(md) → story_parser（Epic/Sprint/As a + Gherkin）→ Scenario 落库
   → RAG 注入（历史相似用例 + test_knowledge 知识片段）
   → LLM 生成：① 手动用例 ② UI 自动化（页面感知）③ 接口自动化（Swagger）
   → execute_cases(auto_heal=True) → 失败自愈（规则 → 向量定位器 → LLM / API 断言）
   → 归档导出：Excel(手动) / pytest 工程(自动化) / JSON
```

### 三类用例生成

- **手动用例**：`ManualCase` schema，AI 产出步骤 + 预期结果（≥ Gherkin 场景数）。
- **UI 自动化**：`generation.fetch_page_snapshot` 抓目标页元素注入 prompt，产出弹性定位器
  （`#id`、`[placeholder=...]`、`button:has-text("登录")`、`text="登录成功"`）。
- **接口自动化**：Swagger → 每 endpoint 生成 正常/缺参/边界 场景，断言含 `status_equals` + `json_schema` + `json_field`；
  Story `关联接口` 由 LLM 生成。

### Swagger 摄取
`openapi_parser`（`fetch_spec` / `$ref` / `parse_endpoints` / `endpoints_to_scenarios`）→
`swagger_service.import_swagger_for_doc` 落库 `Scenario(source="swagger")`；离线演示时 mock 提供 `/v3/api-docs`。

### 归档导出
`manage.py export_cases <batch_id> [--format xlsx|pytest|json|all]`，Web `/batches/<id>/export/<fmt>/`：
- **xlsx**：手动用例 Excel（openpyxl）
- **pytest**：自动化工程 zip（`conftest.py` + Playwright UI + httpx API + jsonschema + requirements/README/manifest）
- **json**：全量存档

### 自愈增强
- **向量定位器库** `locator_history`：成功修复回写，失败时检索复用。
- **LLM selector 候选**：`self_heal_repair`(high) → 快照候选校验 → 应用。
- **API 断言自愈**：值漂移刷新 expected（`assertion_refresh`）、字段重命名修正 path（`field_rename`）。
- **指标**：`manage.py heal_stats` 打印 (失败模式 → 策略) 成功率。

### Web 审核界面
- `/` 项目列表（文档 + 批次）
- `/docs/upload/` 上传需求文档
- `/docs/<id>/` 场景审核列表
- `/scenarios/<id>/edit/` 编辑场景（标题/优先级/自动化/规则/数据）
- `/batches/<id>/` 批次进度（手动/自动化分栏 `?kind=` + 重新运行 + 失败步骤 + 自愈经验 + 导出）
- `/batches/<id>/report/` 执行报告

### RAG 接入（生成 + 自愈）
- 生成：`retrieved_cases`（历史相似用例）+ `retrieved_knowledge`（`test_knowledge`）注入 prompt。
- 自愈：`retrieve_similar_failures` / `retrieve_heal_experience` / `retrieve_locator`。
- `RAG_EMBEDDER=bge` + embedding 服务可切真实语义；`RAG_ENABLED=0` 或 Qdrant 不可达时降级不阻断。

> Phase J 各文件的职责、关键符号与改动注意事项见 [`docs/CODE_FILES.md`](docs/CODE_FILES.md)。

## 测试

```bash
pytest -q                     # 103 passed
cd platform && python manage.py check
```
