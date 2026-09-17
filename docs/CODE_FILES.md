# 代码文件功能说明（人工修改 / 审核用）

> 适用范围：本仓库全部源代码文件。
> 目的：说明每个文件的职责、关键符号、依赖关系与改动注意事项，便于人工审核与二次开发。
> 维护约定：新增/删除文件时请同步更新本文档；"阶段"标注对应 `plan.md` 中的 Phase C–J。

---

## 0. 总览与数据流

**Phase I/J 主链路（需求文档 → 用例 → 执行 → 自愈 → 导出）**：

```
Jira Story / Markdown 文档
  │  core.parsers（markdown_parser / story_parser / openapi_parser）
  ▼
RequirementDoc + Scenario（core.models）
  │  core.services.doc_service.parse_doc / swagger_service.import_swagger_for_doc
  ▼
core.services.generation_service.generate_from_doc
  │   ├─ planner（agent.graph）: RAG 检索历史用例 + 知识库
  │   ├─ generator（agent.generation）: LLM 生成 手动 / UI / 接口 用例（注入 few-shot + 页面快照）
  │   └─ reporter（agent.graph）: 写 testcases.TestCase（kind/test_type/scenario）
  ▼
executor.execute_cases(auto_heal=True)（Playwright MCP / api_server MCP）
  │   └─ 失败 → selfheal.engine.run（analyzer → fixer → 重跑 → learner）
  ▼
TestGenerationBatch 计数 + TestRun JSON/HTML 报告
  │  core.services.export_service（xlsx / pytest zip / json）
  ▼
core.views Web（上传 / 场景审核 / 批次分栏 / 运行 / 报告 / 导出）
```

**Phase C–G legacy 链路**（仍在仓库中，供参考/兼容）：

```
需求文本 → agent.graph.build_demo_graph（planner→generator(echo MCP)→reporter→executor→healer）
```

**RAG 向量流**（Phase G + J）：
- `TestCase` 保存 → `rag/indexer.index_testcase` → collection `testcases`
- `TestStepResult` 失败 → `index_failure` → `step_results`
- `SelfHealLog` 保存 → `index_heal_log` → `heal_logs`
- 定位器修复成功 → `index_locator` → `locator_history`
- 知识库（PRD/接口规范）→ `test_knowledge`（读取通过 `retrieve_knowledge`）

**技术栈**：Django + DRF、LangGraph、DeepSeek Flash（litellm）、qdrant-client、MCP Python SDK（stdio/SSE）、Playwright、PostgreSQL、openpyxl、jsonschema。

---

## 1. 根目录

| 文件 | 作用 | 备注 |
|---|---|---|
| `README.md` | 项目介绍、实现状态、目录结构、快速开始、Phase I/J 使用 | 需与实现同步 |
| `QUICKSTART.md` | 更详细的启动 / API 调用示例 | 含 RAG `/retrieve` 示例 |
| `plan.md` | 各阶段执行计划、环境偏差、验证记录、Phase J 实施进展 | 改动决策来源 |
| `docs/CODE_FILES.md` | 本文档 | — |
| `.env.example` | 环境变量模板（模型、DB、Qdrant、Embedding、RAG） | 复制为 `platform/.env` |
| `.gitignore` | 忽略 `.env`、venv、`media/`、`.qdrant_local/` 等 | 勿把密钥/索引数据入库 |
| `docker-compose.yml` | Qdrant + PostgreSQL + Redis 编排 | 无 Docker 时本地嵌入式 Qdrant 兜底 |
| `pytest.ini` | pytest 配置：`pythonpath=platform`、`testpaths=tests`、`asyncio_mode=strict` | 测试从仓库根运行 |
| `architecture.png` / `cost_comparison.png` / `self_heal_flow.png` | 由 `scripts/generate_diagrams.py` 生成的图 | 非代码 |

---

## 2. `opencode/`（开发态 OpenCode 配置）

| 文件 | 作用 |
|---|---|
| `opencode.json` | OpenCode 主配置：默认模型 `deepseek/deepseek-flash`，挂载官方 Playwright MCP。 |
| `config.yaml` | 团队/文档用完整配置：模型与价格、`router` 规则（low/high 正则）、MCP server 清单、Skills、Agent 模式、成本与隐私控制。与 `apps/agent/router.py::TASK_ROUTING` 语义对齐。 |
| `skills/test-generator/SKILL.md` | Skill：需求 → RAG → LangGraph → 用例/代码/报告。 |
| `skills/self-heal/SKILL.md` | Skill：失败 → 五段自愈闭环 → 自动开 PR。 |

> 审核点：`config.yaml` 与 `router.py` 路由规则须保持一致。

---

## 3. `platform/config/`（Django 工程配置）

| 文件 | 作用 | 修改注意 |
|---|---|---|
| `settings.py` | 全部 Django 配置：`INSTALLED_APPS`、数据库、DRF、CORS、`AGENT_CONFIG`、`RAG_CONFIG`、`MCP_CONFIG_FILE`、`MEDIA_*`（报告/导出落 `media/`）；启动 `load_dotenv(platform/.env)`。 | 新增 app 必须登记 `INSTALLED_APPS`。 |
| `urls.py` | 顶层路由：`/admin/`、`/api/schema`、`/api/docs/`、`/api/v1/` 聚合各 app；**Phase I/J 将 `apps.core.urls.web_urlpatterns` 挂到站点根**；DEBUG 下挂 `media/`。 | 新增 app 需在此 `include`。 |
| `asgi.py` / `wsgi.py` | ASGI/WSGI 入口。 | `DJANGO_SETTINGS_MODULE=config.settings`。 |

---

## 4. `platform/apps/core/`（项目管理 + 产品化链路，Phase I/J 核心）

| 文件 | 作用 | 关键内容 |
|---|---|---|
| `models.py` | 6 个模型：`Project`（`base_url`/`api_base_url`/`swagger_url`）、`RequirementDoc`（file/parsed_scenarios/status）、`Scenario`（story_key/epic/sprint/module/test_types/priority/story_points/role/goal/benefit/business_rules/test_data/acceptance/automation/api_ref/api_spec/env/tags/source）、`TestGenerationBatch`（total/generated/manual_count/automated_count/executed/healed/run/case_ids）、`ExportJob`、`LLMCall`。 | `Scenario.source` = `story`/`markdown`/`swagger`。 |
| `parsers/base.py` | `BaseParser`（`parse(text)->list[dict]`、`supports(file_type)`）。 | 场景 dict 结构见 docstring。 |
| `parsers/markdown_parser.py` | 通用 Markdown：标题层级→场景，`type: api` 启发式（HTTP 动词/API 关键词），```json 规格块，优先级/标签/验收标准。 | 被 `parser_factory` 作为默认。 |
| `parsers/story_parser.py` | **Jira Story**：Epic/Sprint/Story 元数据、`As a/I want/So that`、业务规则、测试数据、**Gherkin AC**、DoD、automation、api_ref、env；`looks_like_story()` 文本特征。 | 由 `get_parser(type, text)` 命中。 |
| `parsers/openapi_parser.py` | **Swagger/OpenAPI**：`fetch_spec`（公开 spec，JSON/YAML）、`resolve_refs`、`parse_endpoints`、`endpoints_to_scenarios`（正常/缺参/边界；`json_schema` 断言；请求体由 schema 示例生成）。 | 仅公开可访问 spec；`$ref` 本地解析。 |
| `parsers/parser_factory.py` | `get_parser(file_type, sample_text=None)`、`supported_file_types()`：按类型/文本特征选 Story/Markdown。 | 不支持类型抛 `ValueError`。 |
| `services/doc_service.py` | `parse_doc(doc_id)`：读文件 → 选解析器 → 写回 `parsed_scenarios` + 幂等重建 `Scenario` 行 + 状态。 | `_save_scenarios` 先删后建。 |
| `services/generation_service.py` | `generate_from_doc(doc_id, ...)`：加载 Scenario → 逐场景调 `build_generation_graph` → `execute_cases(auto_heal)` → 回写批次计数；`scenario_to_dict` 注入 `scenario_id`。 | 仅自动化用例参与执行。 |
| `services/swagger_service.py` | `import_swagger_for_doc(doc, url, base_url)`：拉取/解析/落库 `Scenario(source="swagger")`，失败不阻断。 | best-effort。 |
| `services/export_service.py` | 归档导出：`build_xlsx`（手动用例）、`build_pytest_zip`（UI Playwright + API httpx + jsonschema）、`build_json`、`export_batch(batch_id, fmt)` 写 `ExportJob`。 | 纯渲染函数不依赖 DB，便于单测。 |
| `mock_api.py` | 离线 API 夹具：登录业务规则（/login）、/health、`/v3/api-docs` 公开 spec；`start_mock_api()`。 | 供 `process_doc` 无外部依赖演示。 |
| `views.py` | DRF `ProjectViewSet` + Web：`ProjectListView`/`DocUploadView`/`DocDetailView`/`ScenarioEditView`/`BatchDetailView`/`BatchRunView`/`BatchExportView`/`ReportView`；后台线程 `_start_generation`/`_start_rerun`。 | Web 视图无鉴权（单人本地）。 |
| `urls.py` | DRF router（`/api/v1/projects/`）+ `web_urlpatterns`（站点根：`/`、`/docs/...`、`/scenarios/<id>/edit/`、`/batches/<id>/{,report,run,export}`）。 | 在 `config/urls.py` 注册。 |
| `serializers.py` | `ProjectSerializer`（含 base/api/swagger_url）。 | — |
| `admin.py` | 注册 Project/RequirementDoc/Scenario/TestGenerationBatch/ExportJob/LLMCall。 | — |
| `management/commands/process_doc.py` | 一键：解析 →（Swagger 导入/离线夹具）→ 生成 → 执行 → 自愈；打印场景/batch/TestRun/报告。 | 参数 `--no-execute/--no-heal` 等。 |
| `management/commands/export_cases.py` | `export_cases <batch_id> [--format xlsx|pytest|json|all]`。 | — |
| `migrations/0001..0006` | 0001 Project；0002 base/api/swagger_url + RequirementDoc + TestGenerationBatch；0003 Scenario；0004 LLMCall；0005 Scenario.api_spec/source；0006 batch 计数 + ExportJob。 | 改模型需补迁移。 |

---

## 5. `platform/apps/testcases/`（用例库）

| 文件 | 作用 | 关键内容 |
|---|---|---|
| `models.py` | `TestCase`：`project`(FK)/`project_key`、title、preconditions、steps、assertions、priority、tags、source；**Phase J** `kind`(manual/automated)、`test_type`(functional/ui/api)、`module`、`scenario`(FK)、`manual_steps`、`expected_result`；`target_url`/`raw_steps`；`last_run_*` 为 DEPRECATED 摘要。 | 保存触发 `rag` 的 `post_save` 索引。 |
| `serializers.py` | `TestCaseSerializer`：暴露 `project`，`project_id` 为 `project_key` 别名（兼容旧 API）。 | — |
| `views.py` | `TestCaseViewSet`，支持 `?project_id=`（映射 `project_key`）。 | — |
| `admin.py` | `TestCaseAdmin`（kind/test_type/module/project 过滤）。 | — |
| `migrations/0001..0005` | 0002 `target_url/raw_steps/last_run_*`；0003 deprecated；**0004 加 `project` FK + `project_id`→`project_key`**；**0005 kind/test_type/module/scenario/manual_steps/expected_result**。 | — |

---

## 6. `platform/apps/rag/`（RAG）

> 同时存在**旧知识库 RAG**（`service.py`，collection `test_knowledge`）与 **Phase G/J 业务检索**（`embedder/retriever/indexer/signals`），相互独立。

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `embedder.py` | `Embedder` 协议；`FakeEmbedder(dim=8)` 开发用；`BGEEmbedder` 生产用（OpenAI 兼容）；`get_embedder()` 按 `RAG_EMBEDDER=fake|bge`。 | 无真实模型时默认 fake。 |
| `retriever.py` | `retrieve(query, collection, top_k)`；业务方法 `retrieve_similar_cases` / `retrieve_similar_failures` / `retrieve_heal_experience` / **`retrieve_knowledge`** / **`retrieve_locator`**；async 包装 `aretrieve_similar_cases` / `aretrieve_knowledge`。collection 常量：`testcases`/`step_results`/`heal_logs`/**`test_knowledge`**/**`locator_history`**。`QDRANT_MODE=auto` 远端不可达回退本地。 | 异常一律返回 `[]`。 |
| `indexer.py` | `index_testcase/index_failure/index_heal_log` + **`index_locator`** + 批量 `index_failures`；`schedule_*`（`RAG_INDEX_ASYNC=1` 后台线程）+ `flush()`。 | best-effort；point id 幂等。 |
| `signals.py` | `post_save`：TestCase→`schedule_testcase`；失败 TestStepResult→`schedule_failure`；SelfHealLog→`schedule_heal_log`。 | `bulk_create` 不触发。 |
| `service.py` | **旧知识库**：`Document`/`RetrievalResult`、`embed`、`rerank`、`ingest_document`、`retrieve`、`_split_text`。 | ⚠️ `retrieve` 仍用已移除的 `client.search`；真实调用会失败，新功能请走 `retriever.retrieve_knowledge`。 |
| `views.py` / `urls.py` | `IngestView` / `RetrieveView`（`/api/v1/rag/*`）。 | — |
| `apps.py` | `RagConfig.ready()` 注册 signals。 | — |

---

## 7. `platform/apps/agent/`（LangGraph 编排 + LLM 生成）

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `state.py` | `AgentState`：`requirement`、`project_id`、`retrieved_context`、`retrieved_cases`、**`retrieved_knowledge`**、`test_cases`、`plan`/`saved_ids`、**`scenario`/`case_type`/`project_ref_pk`/`api_base_url`/`ui_target_url`/`source`**、`execute`/`execution_*`、自愈字段。 | 节点返回即状态增量。 |
| `graph.py` | 三套图：<br>① `build_graph()` legacy 完整 9 节点（多为桩）。<br>② `build_demo_graph()` Phase C–G（`generator_node` 现改走 LLM）。<br>③ **`build_generation_graph()`（planner→generator→reporter）** 与 **`build_full_graph()`（+executor 自动自愈）** + `run_full_workflow`。`planner_node` 检索历史用例 + 知识库；`generator_node` 调 `generation.generate_for_scenario`；`reporter_node`/`_save_test_cases` 写新字段与 `scenario` FK。 | 单例 `get_*_graph()`。 |
| `generation.py` | **LLM 生成核心**：`extract_json`、`call_structured`（JSON 提取 + pydantic 校验 + 一次修复）、`generate_for_scenario`（按 automation 生成三类）、`_api_cases_from_spec`（Swagger 确定性）、`fetch_page_snapshot`（页面感知）、`record_llm_call`、`dedup`/`fingerprint`、`resolve_automation`、`default_ui_target`。 | 不调用真实 LLM 时可 monkeypatch `call_llm` 单测。 |
| `schemas.py` | `ManualStep/ManualCase/ManualCaseList`、`UIStep/UIAssertion/UICase/UICaseList`、`ApiAssertion/ApiCase/ApiCaseList`、`SCHEMA_BY_KIND`。 | pydantic v2。 |
| `prompts/__init__.py` | `scenario_context` + `build_manual_prompt` / `build_ui_prompt` / `build_api_prompt`（注入历史用例 few-shot、知识片段、页面元素）；`MANUAL/UI/API_SYSTEM`。 | UI 提示强制 `button:has-text` / `text="..."`。 |
| `llm.py` | `call_llm`（litellm 优先，缺失 httpx 直连）、`_reasoning_kwargs`（DeepSeek：low 关闭 thinking、high 开启 + `reasoning_effort`）、`call_with_retry`。 | thinking 开启会占 `max_tokens`。 |
| `router.py` | Flash-Only 路由：`ReasoningLevel`、`ModelConfig`、`TASK_ROUTING`、`route()`、`CostTracker`。 | 需 `DEEPSEEK_API_KEY`。 |
| `nodes.py` | legacy 完整图节点（多处 TODO），`retrieve_node` 调旧 `rag.service`。 | 与 graph.py demo 节点无关。 |
| `management/commands/run_agent_demo.py` | Phase C–G 演示命令。 | — |
| `management/commands/llm_smoke.py` | 真实 LLM 冒烟：`--structured` 校验 pydantic 结构化输出。 | 需 API key。 |
| `views.py` / `urls.py` | `/api/v1/agent/{generate,heal,cost}`。 | — |

---

## 8. `platform/apps/mcp/`（MCP Client + API）

| 文件 | 作用 | 备注 |
|---|---|---|
| `client.py` | `MCPClient`（stdio + SSE，按 `servers`/`MCP_ENABLED_SERVERS` 过滤）、`call_tool`/`list_tools`；便捷函数。 | `_resolve_command` 用当前解释器保证 venv。 |
| `config.json` | server 注册：`echo`/`playwright`/`api`/`db`/`git`（stdio）+ `wharttest_tools`（SSE）。 | — |
| `views.py` / `urls.py` | `GET /api/v1/mcp/tools`。 | — |

---

## 9. `platform/apps/executor/`（执行器 + 结果模型 + 报告）

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `executor.py` | `execute_case`/`execute_cases(..., auto_heal=False)`：建 `TestRun`，逐条驱动。**UI 分支**（Playwright MCP：navigate/fill/click/select/check/hover/press/wait_for/wait），**API 分支**（`_run_api_case` 经 `api_server.send_request`；`_run_api_assertions` 支持 status/json_field/json_contains/json_path_exists/**json_schema**）；失败步骤 `_capture_failure` 截图；手动用例跳过；`_auto_heal` 触发 `selfheal.engine.run` 并统计 healed。 | `bulk_create` 不触发信号，失败索引显式完成。 |
| `models.py` | `TestRun`、`TestStepResult`（含 `screenshot_path`）。 | 失败样本来源。 |
| `report.py` | `build_report_payload`/`write_report`（`media/reports/run_{id}.json|html`）。 | — |
| `admin.py` | TestRun（内联步骤 + 报告链接）、TestStepResult。 | — |
| `views.py` / `urls.py` | 兼容旧接口 `/api/v1/executor/*`。 | — |

---

## 10. `platform/apps/selfheal/`（自愈）

| 文件 | 作用 | 关键符号 / 备注 |
|---|---|---|
| `analyzer.py` | `classify` / `FailureFeature` / `analyze_step` / `analyze_case`（取最近失败并检索同类历史失败）。 | 关键词表常量。 |
| `fixer.py` | `apply_fix`：**API 用例走 `_fix_api_assertion`**（`assertion_refresh` 值漂移 / `field_rename` 字段重命名）；UI 走规则：`_fix_selector`（snapshot 模糊匹配，成功后 `_record_locator`）→ 失败回退 **`_vector_locator_fix`**（`retrieve_locator`）→ 再回退 **`_llm_selector_fix`**（快照候选 + LLM high/low，校验后应用并回写定位器库）；`_fix_assertion`/`_fix_timing`；`_heal_experience`。 | 直接改写 `raw_steps/steps/assertions` 并落库。 |
| `learner.py` | `record(...)` 累加 `SelfHealLog`。 | — |
| `engine.py` | ① `SelfHealEngine`/`heal_failure` 五段（文档化，向量/LLM/PR 部分为桩）；② **`run(case_id, failed_step_ids)`** 实际可跑：analyze → fix → `execute_case` 重跑 → record。 | `executor._auto_heal` 调用 `run()`。 |
| `models.py` | `SelfHealLog`（pattern/strategy 成功率）。 | — |
| `admin.py` | `SelfHealLogAdmin`。 | — |
| `management/commands/heal_stats.py` | `manage.py heal_stats` 打印 (失败模式 → 策略) 成功率。 | Phase J。 |
| `views.py` / `urls.py` | `POST /api/v1/selfheal/heal`。 | — |

---

## 11. `mcp_servers/`（MCP Server，均 stdio + `MCPServer` 高层 API）

| 文件 | 作用 | 工具 / 备注 |
|---|---|---|
| `echo_server.py` | 确定性假数据：`echo`、`fake_generate_test`（few-shot 复用 selector）。 | 保留供 demo/测试；**Phase J 生成不再依赖它**。 |
| `playwright_server.py` | 真浏览器（headless，懒加载复用）：`navigate/click/fill/select/check/hover/press/wait_for/screenshot/snapshot/get_text/assert_text/assert_visible/get_locator/run_tests/close`。默认超时 1s（便于自愈），浏览器缺失返回 `{"error":...}`。 | Phase J 新增 select/check/hover/press/wait_for/screenshot。 |
| `api_server.py` | 接口测试：`request`、**`send_request`**（executor 用）、`assert_status`、`assert_json`、`load_openapi`。 | 依赖 httpx/jsonpath_ng。 |
| `db_server.py` | `query`/`assert_count`/`assert_exists`（asyncpg）。 | — |
| `git_server.py` | `create_branch`/`commit_changes`/`create_pull_request`（gh/API）。 | 需 `GITHUB_TOKEN/REPO`。 |
| `fixtures/login.html` | 本地登录页（`file://`）；`#phone/#code/#submit/#result`，验证码=123456→登录成功，其它→验证码错误，含 `#slow-submit`。 | 供真执行 / 自愈 / 页面感知演示。 |

---

## 12. `templates/`（Web 与需求模板）

| 文件 | 作用 |
|---|---|
| `core/base.html` | Bootstrap 5 布局 + 导航。 |
| `core/projects.html` | 项目列表（文档链接 + 批次）。 |
| `core/upload.html` | 上传需求文档表单。 |
| `core/doc_detail.html` | 文档 → 场景审核列表 + 批次。 |
| `core/scenario_edit.html` | 场景编辑（标题/模块/优先级/标签/自动化/规则/测试数据）。 |
| `core/batch_detail.html` | 批次进度：手动/自动化分栏、重新运行、失败步骤、自愈经验、导出按钮、报告链接；未完成自动刷新。 |
| `requirements/story_template.md` | **Jira Story 需求模板**（Epic/Sprint/Story + Gherkin + 自动化开关）。 |

---

## 13. `scripts/`（运维 / 初始化脚本）

| 文件 | 作用 | 备注 |
|---|---|---|
| `init_qdrant.py` | 初始化旧知识库 collection + `seed_demo` + 校验路由。 | 针对 `rag.service`（旧链路）。 |
| `seed_demo.py` | 导入 PRD/接口/缺陷示例文档到旧知识库。 | 同上。 |
| `generate_diagrams.py` | 生成 `architecture.png` 等（matplotlib）。 | — |

> Phase G/J 的 `testcases/step_results/heal_logs/locator_history` 通过保存钩子增量写入，无批量回填脚本。

---

## 14. `tests/`

| 文件 | 作用 | 覆盖 |
|---|---|---|
| `test_e2e.py` | 端到端/模块：完整工作流（mock）、五段自愈、成本、旧 RAG、Flash 路由、MCP 配置、失败分类、selector 模糊匹配。 | — |
| `test_rag_phase_g.py` | Phase G：Embedder、三业务方法、降级、planner 注入、fixer 经验、indexer、echo few-shot。 | — |
| `test_phase1_pipeline.py` | Phase I：Markdown 解析、工厂、图编译、API JSON 断言工具。 | — |
| `test_story_parser.py` | Jira Story 解析（元数据/Gherkin/automation/env/工厂选择）。 | — |
| `test_openapi_parser.py` | Swagger：refs/endpoints/scenarios（正/负/边界）、确定性 API 用例、json_schema 断言。 | — |
| `test_generation.py` | LLM 生成：JSON 提取、schema、prompts、automation、normalize、dedup、call_structured 修复、generate_for_scenario。 | — |
| `test_rag_injection.py` | RAG 注入 prompt、planner 知识检索与容错、知识 collection 常量、降级。 | — |
| `test_export.py` | 导出：safe_name、manual_rows、UI/API 代码渲染、xlsx/pytest zip/json 产物。 | — |
| `test_heal_enhance.py` | 自愈增强：selector 提取、字段改名、API 断言刷新、定位器库。 | — |
| `fixtures/` | `sample_requirements.md`（MD 场景）、`story_requirements.md`（Jira）、`openapi_sample.json`（Swagger）。 | — |

> 运行：从仓库根 `pytest -q`（`pytest.ini` 设 `pythonpath=platform`、`testpaths=tests`）。当前 **103 passed**。

---

## 15. 数据模型 / 迁移速查

| 模型 | app | 作用 | 相关迁移 |
|---|---|---|---|
| `Project` | core | 项目（含 base/api/swagger_url） | `core/0001`→`0002` |
| `RequirementDoc` | core | 需求文档 | `core/0002` |
| `Scenario` | core | 解析场景（含 api_spec/source） | `core/0003`→`0005` |
| `TestGenerationBatch` | core | 生成批次（计数 + run + case_ids） | `core/0002`→`0006` |
| `ExportJob` | core | 导出任务 | `core/0006` |
| `LLMCall` | core | LLM 调用/成本 | `core/0004` |
| `TestCase` | testcases | 用例（kind/test_type/scenario/...） | `testcases/0001`→`0004`→`0005` |
| `TestRun` / `TestStepResult` | executor | 执行批次 / 步骤明细 | `executor/0001` |
| `SelfHealLog` | selfheal | 自愈成功率统计 | `selfheal/0001` |

> `makemigrations --check` 当前应无变更；改模型后必须补迁移。

---

## 16. 关键环境变量（详见 `.env.example` / `settings.py`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | — | 模型路由，缺失时 `route()` 抛错 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 唯一模型，reasoning 分档（low 关闭 thinking / high 开启） |
| `DATABASE_URL` 或 `DB_*` | `ai_test` | PostgreSQL |
| `QDRANT_URL` / `QDRANT_MODE` / `QDRANT_LOCAL_PATH` | `auto` / `platform/.qdrant_local` | 远端优先→本地兜底 |
| `RAG_ENABLED` | `1` | `0` = 检索/写入全降级 |
| `RAG_EMBEDDER` / `RAG_FAKE_DIM` | `fake` / `8` | `bge` 为生产 |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `localhost:8000/v1` / `BAAI/bge-m3` / `1024` | BGE |
| `RAG_INDEX_ASYNC` | `0` | `1` = 后台线程写入 |
| `MCP_CONFIG` / `MCP_ENABLED_SERVERS` | — | MCP 配置 / server 子集 |
| `RETRY_BUDGET` / `DAILY_BUDGET` | `3` / `10.0` | 成本保护 |

---

## 17. 人工修改 / 审核清单（重点）

1. **三套解析器**：`markdown_parser`（通用）/ `story_parser`（Jira，`looks_like_story` 命中）/ `openapi_parser`（Swagger）。`parser_factory.get_parser(type, text)` 会按文本特征选 Story；新增格式请在此注册。
2. **Swagger 用例为确定性生成**（`generation._api_cases_from_spec`，不走 LLM）；Story 的 `关联接口` 才走 LLM。二者勿混。
3. **手动 vs 自动化**：`TestCase.kind` 区分；`execute_cases` 只执行 `automated`；手动用例进 Excel 导出。
4. **两套自愈勿混淆**：`engine.run()`（真实可跑）与 `SelfHealEngine.heal()/heal_failure()`（文档化五段，部分桩）。
5. **两套图勿混淆**：`build_graph()`（legacy 桩）/ `build_demo_graph()`（Phase C–G）/ `build_generation_graph()`+`build_full_graph()`（Phase I/J）。
6. **两套 RAG**：`rag/service.py`（旧，`client.search` 已失效）与 Phase G/J `embedder/retriever/indexer`；知识库读取用 `retrieve_knowledge`。
7. **LLM thinking**：DeepSeek Flash 默认开启 thinking 会占满 `max_tokens` 导致 content 为空；`llm._reasoning_kwargs` 对 low 关闭、high 开启。
8. **信号 vs bulk_create**：`TestCase`/`SelfHealLog` 用 `post_save`；`TestStepResult` 走 `bulk_create`，失败索引在 `executor._index_failed_steps` 显式完成。
9. **Qdrant 降级**：所有 RAG 操作 best-effort（异常返回空/跳过），不得阻断主流程。
10. **模型维度一致性**：切换 `RAG_EMBEDDER`（fake 8 ↔ bge 1024）后 collection 会重建，历史向量需重写（无回填脚本）。
11. **密钥安全**：`.env` 已在 `.gitignore`，提交前确认未纳入密钥/索引数据。
