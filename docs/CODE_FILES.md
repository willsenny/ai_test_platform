# 代码文件功能说明（人工修改 / 审核用）

> 适用范围：本仓库全部源代码文件。
> 目的：说明每个文件的职责、关键符号、依赖关系与改动注意事项，便于人工审核与二次开发。
> 维护约定：新增/删除文件时请同步更新本文档；"阶段"标注对应 `plan.md` 中的 Phase C–G。

---

## 0. 总览与数据流

```
需求文本
  │
  ▼
[Django] apps/agent/graph.py  ── planner ──▶ [RAG] apps/rag/retriever.py（检索历史用例）
  │                                     │
  │                                     ▼
  │                             generator（MCP echo: fake_generate_test，注入 few-shot）
  │                                     │
  │                                     ▼
  │                             reporter（写 apps/testcases/TestCase）
  │                                     │
  │                                     ▼
  │                             executor（apps/executor/executor.py + Playwright MCP）
  │                                     │
  │                          失败 ──────┴────── 通过 → finalize
  │                           │
  │                           ▼
  │                    healer（apps/selfheal/engine.py：analyzer → fixer → 重跑 → learner）
  │                           │
  │                           ▼
  └───────────────── 经验写 SelfHealLog + 向量化到 Qdrant
```

**RAG（Phase G）三条向量流**：
- `TestCase` 保存 → `rag/indexer.index_testcase` → collection `testcases`
- `TestStepResult` 失败 → `rag/indexer.index_failure` → collection `step_results`
- `SelfHealLog` 保存 → `rag/indexer.index_heal_log` → collection `heal_logs`

**技术栈**：Django + DRF、LangGraph、qdrant-client、MCP Python SDK（stdio/SSE）、Playwright、PostgreSQL。

---

## 1. 根目录

| 文件 | 作用 | 备注 |
|---|---|---|
| `README.md` | 项目介绍、目录结构、快速开始 | 需与实现同步 |
| `QUICKSTART.md` | 更详细的启动 / API 调用示例 | 含 RAG `/retrieve` 示例 |
| `plan.md` | 各阶段执行计划、环境偏差、验证记录 | Phase C–G 历史，改动决策来源 |
| `.env.example` | 环境变量模板（模型、DB、Qdrant、Embedding、RAG） | 复制为 `platform/.env` 使用 |
| `.gitignore` | 忽略 `.env`、venv、`media/`、`.qdrant_local/`、`qdrant_data/` 等 | 勿把 `.env` / 索引数据入库 |
| `docker-compose.yml` | Qdrant + PostgreSQL + Redis 编排 | 本机无 Docker 时用本地嵌入式 Qdrant 兜底 |
| `pytest.ini` | pytest 配置：`pythonpath=platform`、`testpaths=tests`、`asyncio_mode=strict` | 测试从仓库根运行 |
| `architecture.png` / `cost_comparison.png` / `self_heal_flow.png` | 由 `scripts/generate_diagrams.py` 生成的图 | 非代码 |
| `docs/CODE_FILES.md` | 本文档 | — |

---

## 2. `opencode/`（开发态 OpenCode 配置）

| 文件 | 作用 |
|---|---|
| `opencode.json` | OpenCode 主配置：默认模型 `deepseek/deepseek-flash`，挂载官方 Playwright MCP。 |
| `config.yaml` | 面向团队/文档的完整配置：模型列表与价格、`router` 规则（low/high 正则）、MCP server 清单、Skills、Agent 模式、成本与隐私控制。与 `apps/agent/router.py` 的 `TASK_ROUTING` 语义对齐。 |
| `skills/test-generator/SKILL.md` | Skill 定义：需求 → RAG → LangGraph → 用例/代码/执行报告。 |
| `skills/self-heal/SKILL.md` | Skill 定义：失败 → 五段自愈闭环 → 自动开 PR。 |

> 审核点：`config.yaml` 与 `router.py` 的路由规则需保持一致，否则"文档与实现漂移"。

---

## 3. `platform/config/`（Django 工程配置）

| 文件 | 作用 | 修改注意 |
|---|---|---|
| `settings.py` | 全部 Django 配置：`INSTALLED_APPS`、数据库（`DATABASE_URL`/`DB_*`）、DRF、CORS、`AGENT_CONFIG`（Flash-Only 模型/预算）、`RAG_CONFIG`（Phase G：enabled/qdrant_mode/collections/score_threshold/embedder）、`MCP_CONFIG_FILE`、`MEDIA_*`。启动时 `load_dotenv(platform/.env)`。 | 新增 app 必须登记 `INSTALLED_APPS`；改 RAG 行为优先改 `RAG_CONFIG` 或环境变量。 |
| `urls.py` | 顶层路由：`/admin/`、`/api/schema`、`/api/docs/`，`/api/v1/` 下聚合各 app；DEBUG 下挂 `media/` 静态访问。 | 新 app 需在此 `include`。 |
| `asgi.py` / `wsgi.py` | ASGI/WSGI 部署入口。 | 部署时 `DJANGO_SETTINGS_MODULE=config.settings`。 |
| `__init__.py` | 包标记。 | — |

---

## 4. `platform/apps/core/`（项目管理，复用 WHartTest）

| 文件 | 作用 | 关键内容 |
|---|---|---|
| `models.py` | `Project` 模型：`name`、`key`（唯一，用于 `project_id` 隔离）、描述、时间戳。 | 所有用例/RAG 都以 `project_id`（即 `key`）做隔离。 |
| `serializers.py` | `ProjectSerializer`（ModelSerializer）。 | — |
| `views.py` | `ProjectViewSet`（ModelViewSet，标准 CRUD）。 | — |
| `urls.py` | DRF DefaultRouter，`/api/v1/projects/`。 | — |
| `admin.py` | `ProjectAdmin` 注册。 | — |
| `apps.py` | `CoreConfig`。 | — |
| `migrations/0001_initial.py` | 初始建表。 | 改模型后 `makemigrations`。 |

---

## 5. `platform/apps/testcases/`（用例库，复用 + 扩充）

| 文件 | 作用 | 关键内容 |
|---|---|---|
| `models.py` | `TestCase` 模型：`project_id`、`title`、`preconditions`、`steps`、`assertions`、`priority`(P0/P1/P2)、`tags`、`source`、`target_url`、`raw_steps`；`last_run_*` 为 **DEPRECATED** 摘要字段（Phase E 起明细在 `executor.TestStepResult`）。 | 保存时会触发 `rag` 的 `post_save` 信号索引到 Qdrant。 |
| `serializers.py` | `TestCaseSerializer`（暴露全部字段）。 | — |
| `views.py` | `TestCaseViewSet`，支持 `?project_id=` 过滤。 | — |
| `urls.py` | Router，`/api/v1/testcases/`。 | — |
| `admin.py` | `TestCaseAdmin`（按优先级/项目/最近状态过滤）。 | — |
| `apps.py` | `TestcasesConfig`。 | — |
| `migrations/0001..0003` | 0001 初始；0002 加 `target_url`/`raw_steps`/`last_run_*`（Phase D）；0003 把 `last_run_*` 标注 deprecated（Phase E）。 | 手工改模型务必补迁移。 |

---

## 6. `platform/apps/rag/`（RAG，Phase G 核心）

> 注意：本 app 同时存在**旧知识库 RAG**（`service.py`，collection `test_knowledge`，带 reranker 占位）
> 和 **Phase G 业务检索**（`embedder/retriever/indexer/signals`，三个新 collection）。二者相互独立。

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `embedder.py` | **Embedder 抽象**。`Embedder` 协议（`dimension`/`embed`/`embed_many`）；`FakeEmbedder(dim=8)` 开发用（确定性哈希词袋，共享 token 相似度更高）；`BGEEmbedder` 生产用（OpenAI 兼容 embeddings HTTP，默认 `BAAI/bge-m3`，可换 `text2vec-large-chinese`）；`get_embedder()` 按 `RAG_EMBEDDER=fake|bge` 返回单例。 | 只依赖 stdlib + httpx；改模型维度用 `EMBEDDING_DIM`。 |
| `retriever.py` | **向量检索**。`retrieve(query, collection, top_k)` → `[{id,payload,score}]`；业务方法 `retrieve_similar_cases` / `retrieve_similar_failures` / `retrieve_heal_experience`；`aretrieve_similar_cases` 为 async 包装。`get_client()` 按 `QDRANT_MODE`（auto/remote/local/memory/off）构建客户端，**auto 默认远端不可达回退本地嵌入式**；`ensure_collection` 维度不符自动重建；所有异常返回 `[]`（降级不阻断）。collection 常量 `testcases`/`step_results`/`heal_logs`。 | 使用 `query_points`（qdrant-client ≥1.19 已移除 `search`）。`atexit` 主动关闭避免退出报错。 |
| `indexer.py` | **向量写入**。`index_testcase/index_failure/index_heal_log` + 批量 `index_failures`；文本化函数 `testcase_text/failure_text/heal_text`；`schedule_*` 支持 `RAG_INDEX_ASYNC=1` 后台线程，`flush()` 收尾。best-effort，异常仅告警。 | point id 用数据库主键（幂等 upsert）。 |
| `signals.py` | Django `post_save` 信号：`TestCase`→`schedule_testcase`；`TestStepResult`（失败态）→`schedule_failure`；`SelfHealLog`→`schedule_heal_log`。 | `bulk_create` 不触发信号，故 executor 另做显式索引。 |
| `apps.py` | `RagConfig.ready()` 导入 `signals` 完成注册。 | 勿在 `ready()` 里做网络/DB 访问。 |
| `service.py` | **旧知识库 RAG**（PRD/接口/历史缺陷入库与检索）：`Document`/`RetrievalResult`、`embed`、`rerank`、`ingest_document`、`retrieve`（`_split_text` 分块）。 | ⚠️ `retrieve` 仍调用已移除的 `client.search`，真实调用会失败；目前仅被 legacy `nodes.retrieve_node` / `scripts/*` 使用且测试中被打桩。改造/清理时注意。 |
| `views.py` | `IngestView`、`RetrieveView`（`/api/v1/rag/ingest`、`/retrieve`）。 | — |
| `urls.py` | RAG 路由。 | — |
| `__init__.py` | 包标记。 | — |

---

## 7. `platform/apps/agent/`（LangGraph 编排）

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `state.py` | `AgentState`（TypedDict）：`requirement`、`project_id`、`retrieved_context`、Phase G `retrieved_cases`/`few_shot_used`、`test_cases`、`plan`/`saved_ids`、`execute`/`execution_*`、`self_heal`/`inject_failure`/`heal_results`、`retry_budget` 等。另含旧 `TestCase` TypedDict。 | 节点返回值即状态增量；新增字段记得加类型。 |
| `graph.py` | 两套图：<br>① `build_graph()` + `run_test_workflow()`：完整 9 节点链路（retrieve→…→self_heal），部分节点为桩。<br>② `build_demo_graph()` + `run_agent_demo_workflow()`：Phase C–G 可跑闭环。节点实现含 `planner_node`（Phase G 检索历史用例+日志）、`generator_node`（MCP echo + few-shot）、`reporter_node`、`executor_node`、`inject_failure_node`、`healer_node`；含 `_few_shot_payload`、`_save_test_cases`、`_inject_failure`。 | 单例缓存 `get_graph()/get_demo_graph()`。 |
| `nodes.py` | **legacy 完整图**的节点实现（understand/design_scenarios/…/self_heal），多处 `TODO`：LLM 调用、向量定位器、PR。`retrieve_node` 调用旧 `rag.service.retrieve`。 | 与 `graph.py` demo 节点互不影响；清理时区分。 |
| `router.py` | **Flash-Only** 模型路由：`ReasoningLevel`、`ModelConfig`、`TASK_ROUTING`、`route(task, force_reasoning, use_local)`、`CostTracker`/`get_cost_tracker()`。 | 需 `DEEPSEEK_API_KEY`；任务名正则映射 low/high。 |
| `llm.py` | LLM 调用适配层：`call_llm`（litellm 优先，缺失则 httpx 直连）、结构化输出、成本记录；`call_with_retry` 指数退避。 | 当前业务链路默认不真正调用 LLM。 |
| `management/commands/run_agent_demo.py` | 演示命令 `python manage.py run_agent_demo`：参数 `--goal/--project-id/--count/--execute/--self-heal/--inject-failure`；打印 planner（含 `[retrieved N similar cases]`）、生成、入库、执行、自愈（含 `[retrieved N similar failures]` / `[heal experience]`）。 | Phase C–G 主要验证入口。 |
| `views.py` | `GenerateTestView`（跑完整图）、`HealView`（五段引擎）、`CostReportView`。 | — |
| `urls.py` | `/api/v1/agent/{generate,heal,cost}`。 | — |
| `apps.py` | `AgentConfig`。 | — |

---

## 8. `platform/apps/mcp/`（MCP Client + API）

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `client.py` | MCP 统一客户端：`MCPClient`（`servers=[...]` 过滤，stdio + SSE，`AsyncExitStack` 管理生命周期）、`call_tool`/`list_tools`；便捷函数 `get_client`/`call_tool`/`run_playwright_test`/`run_api_test`/`query_database`/`create_pr`；`_parse_tool_result`。 | 用 `MCP_ENABLED_SERVERS` 或构造参数按名连接子集；`_resolve_command` 用当前解释器，保证 venv 一致。 |
| `config.json` | MCP server 注册：`echo`/`playwright`/`api`/`db`/`git`（stdio，路径相对仓库根）+ `wharttest_tools`（SSE）。 | 新增 server 在此登记。 |
| `views.py` / `urls.py` | `GET /api/v1/mcp/tools` 列出已连接工具。 | — |
| `apps.py` | `McpConfig`。 | — |

---

## 9. `platform/apps/executor/`（执行器 + 结果模型 + 报告）

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `executor.py` | Phase D/E 执行核心。`execute_case(case_id, run_id=None)`：建/并入 `TestRun`，按 `raw_steps` 驱动 Playwright MCP（navigate/fill/click/wait），按 `assertions` 校验，逐条写 `TestStepResult`，汇总与报告；`execute_cases(case_ids)` 批次执行；Phase G 在 `_bulk_create_step_results` 后 `_index_failed_steps` 把失败步骤写入 Qdrant。兼容旧接口 `execute_ui_test/execute_api_test/query_database`。 | `bulk_create` 不走信号，故需显式索引。 |
| `models.py` | `TestRun`（批次：project/goal/source/status/统计/报告路径/时间）、`TestStepResult`（步骤明细：phase/action/selector/value/expected/actual/status/error/duration_ms，FK 回 TestRun+TestCase）。 | 失败样本来源；被 analyzer 与 RAG 使用。 |
| `report.py` | 报告生成：`build_report_payload`、`write_report`（输出 `media/reports/run_{id}.json|html`）、`_render_html`。 | HTML 用内联 `<style>`，无模板依赖。 |
| `admin.py` | `TestRunAdmin`（内联步骤 + 报告链接）、`TestStepResultAdmin`。 | — |
| `views.py` / `urls.py` | `POST /api/v1/executor/ui/run`、`/api/run` 兼容旧接口。 | — |
| `apps.py` | `ExecutorConfig`。 | — |
| `migrations/0001_initial.py` | 建 TestRun/TestStepResult。 | — |

---

## 10. `platform/apps/selfheal/`（自愈，Phase F 规则驱动 + legacy 五段）

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `analyzer.py` | 失败分析：`classify(phase,expected,actual,error)` → `(failure_type, confidence)`（selector/timing/navigation/text_mismatch）；`FailureFeature` dataclass（含 Phase G `similar_failures`）；`analyze_step`；`analyze_case(case_id)` 取最近一次失败并为每个特征检索同类历史失败。 | 关键词表在 `_SELECTOR_MARKERS` 等常量。 |
| `fixer.py` | 规则修复：`FixResult`（含 Phase G `rag_hint`）；`apply_fix(case_id, feature)` 按类型分派并回写 TestCase；`_fix_selector`（snapshot 模糊匹配重定位）、`_fix_assertion`（回放+get_text 刷新期望）、`_fix_timing`（前插 wait）；`_heal_experience` 检索历史成功策略并对未知失败兜底映射。含匹配工具 `_tokens/_best_match/_selector_for`。 | 直接改写 `raw_steps/steps/assertions` 并落库。 |
| `learner.py` | `record(failure_pattern, fix_strategy, success, ...)`：按 `(failure_pattern, fix_strategy)` 累加尝试/成功次数到 `SelfHealLog` 并返回统计。保存触发 RAG 索引。 | — |
| `engine.py` | 两套：<br>① `SelfHealEngine` + `FailureContext` + `HealResult` + `heal_failure()`：文档化的**五段闭环**（规则→向量定位器→LLM→重跑→PR），向量/LLM/PR 处仍是 `TODO`/桩。<br>② Phase F `run(case_id)`：analyze → fix → `execute_case` 重跑 → `record` 落库；返回含 `rag_failures`/`rag_hint` 的 attempts。 | 实际可跑的是 `run()`；`views.py`/`agent/views.py` 的 `/heal` 走五段 `heal_failure`。 |
| `models.py` | `SelfHealLog`：`failure_pattern`、`fix_strategy`、`attempt_count`、`success_count`、`last_testcase`、`last_detail`、`updated_at`，`unique_together`，`success_rate` 属性。 | Phase G 保存即向量化。 |
| `admin.py` | `SelfHealLogAdmin`（成功率展示）。 | — |
| `views.py` / `urls.py` | `POST /api/v1/selfheal/heal`。 | — |
| `apps.py` | `SelfhealConfig`。 | — |
| `migrations/0001_initial.py` | 建 SelfHealLog。 | — |

---

## 11. `mcp_servers/`（MCP Server 实现，均 stdio + `MCPServer` 高层 API）

| 文件 | 作用 | 工具 / 备注 |
|---|---|---|
| `echo_server.py` | 确定性假数据 server（Phase C 起）。`echo(text)`；`fake_generate_test(goal, count, few_shot)` 生成结构化用例，Phase G 会解析 `few_shot` 并**复用历史 selector 模式**（`_extract_selectors`）。 | 供 demo/测试，不调 LLM。 |
| `playwright_server.py` | 真浏览器（headless Chromium，懒加载复用）：`navigate/click/fill/snapshot/get_text/assert_text/assert_visible/get_locator/run_tests/close`。默认超时 1s，便于自愈拿失败特征；浏览器缺失返回 `{"error": ...}` 不阻断。 | `run_tests` 用 `pytest --json-report`。 |
| `api_server.py` | 接口测试：`request`（httpx）、`assert_status`、`assert_json`（jsonpath_ng）、`load_openapi`（按规范生成正/负用例）。 | 依赖 `httpx`、`jsonpath_ng`。 |
| `db_server.py` | 数据一致性断言：`query`、`assert_count`、`assert_exists`；连接用 `asyncpg`，DSN 取 `DATABASE_URL`。 | 依赖 `asyncpg`。 |
| `git_server.py` | 自愈开 PR：`create_branch`、`commit_changes`、`create_pull_request`（优先 `gh`，回退 GitHub API，需 `GITHUB_TOKEN/GITHUB_REPO`）。 | — |
| `fixtures/login.html` | 本地登录示例页（`file://`，含延迟 3s 的 `#slow-submit`），供真执行 / 自愈演示。 | 不依赖外部服务。 |

---

## 12. `scripts/`（运维 / 初始化脚本，从仓库根运行）

| 文件 | 作用 | 备注 |
|---|---|---|
| `init_qdrant.py` | 初始化旧知识库 collection `test_knowledge` + 调用 `seed_demo` + 校验模型路由。 | 针对 `rag.service`（旧链路），非 Phase G 三个 collection。 |
| `seed_demo.py` | 导入 PRD/接口/缺陷示例文档到旧知识库。 | 同上。 |
| `generate_diagrams.py` | 生成 `architecture.png`/`cost_comparison.png`/`self_heal_flow.png`（matplotlib）。 | 需中文字体。 |

> Phase G 说明：**未提供**历史数据批量回填脚本（按需求"不做"）；`testcases/step_results/heal_logs` 仅通过保存钩子增量写入。

---

## 13. `tests/`

| 文件 | 作用 | 覆盖 |
|---|---|---|
| `test_e2e.py` | 端到端 / 模块测试：完整工作流（mock RAG/LLM）、五段自愈、成本追踪、旧 RAG 分块与空库检索、Flash 路由、MCP 配置、Phase F 失败分类与 selector 模糊匹配。 | 17 条 |
| `test_rag_phase_g.py` | Phase G：FakeEmbedder 维度/确定性/相似性、三业务方法 roundtrip、`RAG_ENABLED=0` 与远端不可达降级、planner 注入历史用例、fixer 命中历史策略、indexer 写入检索、echo few-shot selector 复用。 | 13 条 |
| `pytest.ini` | 测试配置。 | — |

---

## 14. 数据模型 / 迁移速查

| 模型 | app | 作用 | 相关迁移 |
|---|---|---|---|
| `Project` | core | 项目隔离 | `0001` |
| `TestCase` | testcases | 用例（含 raw_steps / target_url） | `0001` → `0002`（Phase D）→ `0003`（Phase E deprecated 标注） |
| `TestRun` / `TestStepResult` | executor | 执行批次 / 步骤明细 | `0001`（Phase E） |
| `SelfHealLog` | selfheal | `(pattern,strategy)` 成功率统计 | `0001`（Phase F） |

> `makemigrations --check` 当前应无变更；改模型后必须补迁移。

---

## 15. 关键环境变量（详见 `.env.example` / `settings.py`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | — | 模型路由，缺失时 `route()` 抛错 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 唯一模型，reasoning 分档 |
| `DATABASE_URL` 或 `DB_*` | `ai_test` | PostgreSQL |
| `QDRANT_URL` / `QDRANT_API_KEY` | `http://localhost:6333` | 远端 Qdrant |
| `QDRANT_MODE` | `auto` | `auto`(远端优先→本地兜底)/`remote`/`local`/`memory`/`off` |
| `QDRANT_LOCAL_PATH` | `platform/.qdrant_local` | 本地嵌入式索引目录 |
| `RAG_ENABLED` | `1` | `0` = 检索/写入全降级 |
| `RAG_SCORE_THRESHOLD` | `0.0` | 仅用 score 阈值过滤（不接 reranker） |
| `RAG_EMBEDDER` | `fake` | `fake`(dim=8) / `bge`(生产) |
| `RAG_FAKE_DIM` | `8` | FakeEmbedder 维度 |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `localhost:8000/v1` / `BAAI/bge-m3` / `1024` | BGE embedder |
| `RAG_INDEX_ASYNC` | `0` | `1` = 向量写入改后台线程 |
| `MCP_CONFIG` / `MCP_ENABLED_SERVERS` | — | MCP 配置路径 / server 子集 |
| `RETRY_BUDGET` / `DAILY_BUDGET` | `3` / `10.0` | 成本保护 |

---

## 16. 人工修改 / 审核清单（重点）

1. **两套 RAG 勿混淆**：`rag/service.py`（旧知识库，含失效的 `client.search`）与 Phase G 的
   `embedder/retriever/indexer/signals`。新功能走 Phase G；若要复用旧知识库需先修 `service.retrieve`。
2. **两套自愈勿混淆**：`selfheal/engine.py::run()`（真实可跑，规则驱动）与
   `SelfHealEngine.heal()/heal_failure()`（文档化五段，向量/LLM/PR 仍为桩）。
3. **两套图勿混淆**：`graph.build_graph()`（legacy 完整图，多节点 TODO）与
   `graph.build_demo_graph()`（Phase C–G 可跑闭环）。
4. **信号 vs bulk_create**：`TestCase`/`SelfHealLog` 用 `post_save`，但 `TestStepResult` 走
   `bulk_create` 不触发信号，失败索引在 `executor._index_failed_steps` 显式完成；新增批量写入时注意。
5. **Qdrant 降级**：所有 RAG 操作必须保持 best-effort（异常返回空/跳过），不得阻断主流程。
6. **无 Docker 环境**：默认 `QDRANT_MODE=auto` 本地嵌入式兜底；`docker-compose` 仅在有 Docker 时使用。
7. **模型维度一致性**：切换 `RAG_EMBEDDER`（fake 8 ↔ bge 1024）后，`ensure_collection` 会因维度不符重建
   collection，历史向量需重新写入（当前无回填脚本）。
8. **密钥安全**：`.env` 已在 `.gitignore`；提交前确认未把密钥/索引数据纳入版本控制。
