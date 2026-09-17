# Phase C — 最小闭环验证（执行计划）

> 目标：证明 **Django → LangGraph → MCP(stdio) → DB** 主链路能跑通。
> 不接浏览器、不接 RAG、不做自愈。

## 环境现实与偏差说明

| 原始步骤 | 状态 | 处理 |
|---|---|---|
| 1. `docker compose up -d` | Docker 未安装 | **替换**：使用本机已运行的 Homebrew PostgreSQL 15（5432）。Qdrant/Redis 跳过（Phase C 不需要 RAG / 队列） |
| 2. `migrate` + superuser + `check` | 无 venv / 无依赖 | 用 Python 3.14 建 `platform/.venv`，只装 Phase C 依赖 |
| 3. `echo_server.py` | 缺失 | 新增 stdio JSON-RPC server |
| 4. MCP client 连 echo | config 硬编码 `/data/workspace`，且会连接所有 server | 支持按名连接子集 + repo 相对路径 |
| 5. planner→generator→reporter | `graph.py` 是完整 RAG 链路 | 新增独立最小图，保留原图 |
| 6. `run_agent_demo` | 不存在 | 新增 management command |
| 7. pytest + check + DB 行 | 依赖未装 | venv 内执行 |

**已确认决策**：本地 Postgres；Python 3.14 + pip venv；generator 用确定性 `fake_generate_test`（不调 LLM）。

## 执行顺序

### 0. 基础设施
- `createdb -h localhost ai_test`（owner `willsen`）。
- `python3.14 -m venv platform/.venv`。
- pip 安装：django / djangorestframework / djangorestframework-simplejwt / django-cors-headers / drf-spectacular / langgraph / langchain-core / pydantic / litellm / httpx / mcp / psycopg[binary] / python-dotenv / pytest / pytest-asyncio。
- 不装：sentence-transformers、playwright、qdrant-client、pydantic-ai。

### 1. Django 配置基线
- `config/settings.py` 加载 `platform/.env`（python-dotenv）；数据库同时支持 `DATABASE_URL` 与 `DB_*`。
- `manage.py migrate` → `createsuperuser --noinput`（admin）→ `manage.py check`。

### 2. `mcp_servers/echo_server.py`
- stdio JSON-RPC（`mcp.server.Server` + `stdio_server`，与 `api_server.py` 同构）。
- Tool：
  - `echo(text) -> text`
  - `fake_generate_test(goal, count=3) -> JSON list[TestCase]`（确定性，字段对齐 `apps.agent.state.TestCase`）。

### 3. MCP client 连 echo
- `MCPClient(servers=[...])` + `MCP_ENABLED_SERVERS` 环境变量过滤。
- `config.json` 增加 `echo` 条目，脚本路径按 repo 根解析。
- 保留 `playwright` / `wharttest_tools` 键，确保 `TestMCPClient` 通过。
- 冒烟：connect echo → `list_tools` → `call_tool("echo", ...)` 与 `fake_generate_test`。

### 4. `apps/agent/graph.py` 三步链路
- `planner_node`：goal → plan（不调 LLM）。
- `generator_node`：`MCPClient(servers=["echo"])` → `fake_generate_test` → `test_cases`。
- `reporter_node`：`sync_to_async` → `TestCase.objects.create` → `saved_ids`。
- `AgentState` 增加可选 `plan` / `saved_ids`；新增 `build_demo_graph` / `run_agent_demo_workflow`。

### 5. `manage.py run_agent_demo`
- `apps/agent/management/commands/run_agent_demo.py`，参数 `--goal` / `--project-id` / `--count`；`asyncio.run` 包装；打印 plan、MCP 输出、saved IDs、DB count。

### 6. 最终验证（完成标准）
- `platform/.venv/bin/pytest tests/ -q`
- `platform/.venv/bin/python manage.py check`
- `psql -d ai_test -c "select count(*) from testcases_testcase;"` 出现新行。

## 不做的事
- 不装 embedding 模型、不接 Qdrant 检索。
- 不写 Playwright 真浏览器。
- 不实现 self-heal。
- 不调真实 LLM。

## 卡点原则
任何一步失败即停止并报告错误，不跳步。

---

## 追加：MCP Server API 统一（Phase C 收尾）

**问题**：`mcp_servers/` 下 server 混用两套 SDK API。`echo_server.py` 用 mcp 2.x 的 `MCPServer`，
而 `api_server.py` / `db_server.py` / `git_server.py` / `playwright_server.py` 仍用已移除的
旧式 `Server` + `@server.list_tools()` / `@server.call_tool()` 装饰器，在当前 `mcp 2.2.0` 下无法启动。

**处理**：4 个旧 server 全部迁移到 `MCPServer` 高层 API，与 `echo_server.py` 保持一致：
- `from mcp.server import MCPServer` → `mcp = MCPServer(name)`。
- `@mcp.tool(name=..., description=...)` + 显式类型注解参数（SDK 自动生成 inputSchema）。
- Tool 返回 JSON 字符串（便于 `MCPClient._parse_tool_result` 提取文本）。
- 入口统一为 `mcp.run("stdio")`。
- 顺带修复：`git_server.py` 缺失 `from pathlib import Path`；`playwright_server.py` 用
  `sys.executable -m pytest` 且移除无效的 `--tb=json`。

**验证**：经 `MCPClient` 连接 `echo/api/db/git` 四个本地 server 列举工具成功；本地
`playwright_server.py` 直接 stdio 调用 `snapshot` / `get_locator` 成功。

**接线切换（已完成）**：`config.json` 的 `playwright` 键已由官方 `npx @playwright/mcp` 切换为本地
`mcp_servers/playwright_server.py`，使自愈代码期望的 `run_tests` / `get_locator` 等工具可用。
配套安装 `pytest-json-report`，并验证本地 playwright server 经 `MCPClient` 调用 `snapshot` 与
`run_tests`（exit_code=0）成功。

---

## 路线图（后续阶段）

| 阶段 | 内容 | 状态 |
|---|---|---|
| **Phase C** | 最小闭环（Fake MCP） | ✅ 已完成 |
| **Phase D** | 真 Playwright MCP | ✅ 已完成（真浏览器执行） |
| **Phase E** | Executor + 测试结果模型 + 报告 | ✅ 已完成 |
| **Phase F** | Self-heal 五段闭环（先用规则，再接 LLM） | ✅ 已完成（规则驱动） |
| **Phase G** | RAG：Qdrant + embedding + 检索（不做 reranker/混合检索） | ✅ 已完成 |
| **Phase H** | 成本 / 日志 / 人类审批 / CI | ⬜ |

---

## Phase D — 生成即执行闭环（已完成）

**范围**：Agent 生成结构化用例 → Playwright MCP 真执行 → 结果回写 DB。不做自愈（F）、不做 RAG（G）。

**实现**：
- `mcp_servers/fixtures/login.html`：本地登录示例页（file://，无需外部服务）。
- `mcp_servers/echo_server.py`：`fake_generate_test` 产出结构化 `steps`（`action`/`selector`/`value`）+ `assertions` + `target_url`，确定性、不调 LLM。
- `mcp_servers/playwright_server.py`：接入真 headless Chromium（`playwright==1.60.0`，复用已有浏览器缓存），工具 `navigate` / `click` / `fill` / `snapshot` / `assert_text` / `assert_visible`；浏览器缺失时返回 `{"error": ...}` 不阻断。
- `TestCase` 新增 `target_url` / `raw_steps` / `last_run_status` / `last_run_log` / `last_run_at`（迁移 `0002`）。
- `apps/executor/executor.py::execute_case(case_id)`：按 `raw_steps` 驱动 MCP、按 `assertions` 校验，`sync_to_async` 回写结果。
- `apps/agent/graph.py`：demo 图增加 `executor` 节点（`execute` 开关）；`run_agent_demo --execute` 生成后自动执行并打印每步动作与 pass/fail。

**验证**：
- `run_agent_demo --goal ... --count 3 --execute` → 3/3 pass，逐条打印 navigate/fill/click/assert 日志。
- DB：`last_run_status=pass`、`last_run_at` 非空、`last_run_log` 含每步明细。
- `pytest tests/ -q` → 12 passed；`manage.py check` → no issues。

**未做**：自愈循环、多用例编排、截图/视频录制、Qdrant 检索；未安装浏览器（复用现有缓存）。

---

## Phase E — 测试结果模型 + 报告（已完成）

**范围**：执行结果从 TestCase 拆出独立建模 + 生成可读报告，为 Phase F 自愈提供失败样本。

**实现**：
- `apps/executor/models.py`：
  - `TestRun`：一次执行批次（project/goal/source/status/total/passed/failed/report 路径/时间）。
  - `TestStepResult`：每个 step/assertion 明细（`phase`/`action`/`selector`/`value`/`expected`/`actual`/`status`/`error`/`screenshot_path`/`duration_ms`），FK 回 `TestRun` 与 `TestCase`。
- `TestCase.last_run_*` 标记 deprecated（help_text + 迁移 `0003`），执行器仍写摘要以便逐步迁移。
- `apps/executor/report.py`：`write_report(run)` 输出 `media/reports/run_{id}.json` + `.html`（用例/步骤/断言/结果/耗时）。
- `apps/executor/executor.py`：`execute_case(case_id, run_id=None)` 写 `TestStepResult` 行（不再只拼文本）；`execute_cases(case_ids)` 建单个 `TestRun` 批次、汇总并生成报告。
- `apps/executor/admin.py`：`TestRun` 注册并内联 `TestStepResult`，可按批次查看步骤明细 + 报告链接；`TestStepResult` 独立注册。
- settings 增加 `MEDIA_URL`/`MEDIA_ROOT`；`config/urls.py` DEBUG 下提供 media 静态访问；`.gitignore` 忽略 `media/`。
- `graph.executor_node` 改用 `execute_cases`，`run_agent_demo --execute` 打印 `TestRun #id` 与报告路径。

**验证**：
- `run_agent_demo --count 2 --execute` → TestRun #1（2/2 pass）；TestStepResult 每步一行（2 用例 × 5 行）。
- `media/reports/run_1.html|json`、`run_2.html|json` 生成；`/media/reports/run_2.html` GET 200。
- admin 已注册 `TestRun` / `TestStepResult`。
- `pytest tests/ -q` → 12 passed；`manage.py check` → no issues。

**未做**：截图/视频录制、定时调度、CI 集成、邮件通知。

---

## Phase F — 自愈五段闭环（规则驱动，已完成）

**范围**：执行失败后自动诊断 → 修复 → 验证 → 沉淀。仅规则，不接 LLM / RAG。

**实现**：
- `apps/selfheal/analyzer.py`：从 `TestStepResult` 提取失败特征并分类
  （`element_not_found`/`text_mismatch`/`timeout`/`navigation_failed` → `suspect_selector/assertion/timing/url`）。
- `apps/selfheal/fixer.py`：
  - selector 变了 → `snapshot` 枚举元素，按 id/name/placeholder/label 模糊匹配重定位 `selector_remap`；
  - 断言过期 → 回放步骤 + `get_text` 取当前值，刷新断言 `expected`（`assertion_refresh`）；
  - timing → 失败步前插入 `wait` 步骤（`timing_wait`）；navigation 暂不支持。
- `apps/selfheal/learner.py` + `SelfHealLog` 模型：按 `(failure_pattern, fix_strategy)` 累计
  `attempt_count/success_count`。
- `apps/selfheal/engine.py::run(case_id)`：分析 → 修复 → `execute_case` 重跑验证 → 写 `SelfHealLog`。
- `graph.healer_node`（`self_heal` 开关）+ `inject_failure_node`（演示注入）；`run_agent_demo`
  新增 `--self-heal` / `--inject-failure {selector,assertion,timing}`。
- `playwright_server.py`：默认动作超时 1s（自愈插入 wait 补偿）、`snapshot` 增补
  placeholder/ariaLabel/label、新增 `get_text`；fixture 增加延迟可用的 `#slow-submit`。
- executor 支持 `wait` 步骤。

**验证（三种失败类型均自愈成功）**：
```
--inject-failure selector  → element_not_found / selector_remap  '#code_old'→'#code'   rerun=pass
--inject-failure assertion → text_mismatch     / assertion_refresh '登录OK'→'登录成功' rerun=pass
--inject-failure timing    → timeout           / timing_wait       插入 3500ms wait    rerun=pass
```
- `selfheal_selfheallog` 三条记录，`success_count=1`。
- `pytest tests/ -q` → 17 passed（新增 5 条规则单测）；`manage.py check` → no issues。

**未做**：LLM 参与分析、RAG 检索历史修复、多轮重试上限以外的高级策略。

---

## Phase G — RAG 检索增强（已完成）

**范围**：Qdrant 存用例/执行历史/自愈经验；agent 生成与自愈时检索相似案例辅助决策。
纯向量检索 + score 阈值，不接 reranker、不做混合检索、不做 embedding 缓存/批量回填。

**环境偏差**：本机无 Docker（沿用 Phase C 记录）。`docker-compose.yml` 的 qdrant 服务保留；
默认 `QDRANT_MODE=auto`：先探测 `QDRANT_URL`，不可达则回退 **qdrant-client 本地嵌入式 store**
（`platform/.qdrant_local/`，与远端同一套 Qdrant API/collection 语义）。装了 `qdrant-client==1.19.0`。

**实现**：
- 依赖：`qdrant-client`（含 numpy/grpcio）。
- `apps/rag/embedder.py`：`Embedder` 协议；`FakeEmbedder(dim=8)`（哈希词袋，确定性、共享 token 相似度高）
  开发用；`BGEEmbedder`（bge-m3 / text2vec-large-chinese，OpenAI 兼容 HTTP）生产用；
  `get_embedder()` 由 `RAG_EMBEDDER=fake|bge` 选择，统一 `embed(text) -> list[float]`。
- `apps/rag/retriever.py`：`retrieve(query, collection, top_k)` → `[{id, payload, score}]`
  （`query_points` + score 阈值过滤）；三个业务方法 `retrieve_similar_cases(goal)` /
  `retrieve_similar_failures(selector, error)` / `retrieve_heal_experience(pattern)`。
  collection：`testcases` / `step_results` / `heal_logs`，维度按 embedder 动态确定；
  维度不符时重建。任何异常返回 `[]`（降级不阻断）；`is_degraded()` 可观测。
- `apps/rag/indexer.py`：`index_testcase/index_failure/index_heal_log`（best-effort，Qdrant 不可用仅告警）；
  默认内联，`RAG_INDEX_ASYNC=1` 时后台线程，`flush()` 收尾。
- `apps/rag/signals.py` + `RagConfig.ready()`：TestCase / SelfHealLog `post_save` 自动写入。
- `apps/executor/executor.py`：`bulk_create` 不触发 signal，执行后显式索引失败 `TestStepResult`。
- 接入点：
  - planner：生成前 `retrieve_similar_cases(goal)` top-3，计划打印 `[retrieved N similar cases]`；
    generator 把历史用例（title+steps）作为 few-shot 传给 `fake_generate_test`。
  - `echo_server.fake_generate_test(..., few_shot)`：按角色复用历史 selector 模式。
  - analyzer：失败时 `retrieve_similar_failures(selector, error)` 附加 `similar_failures`。
  - fixer：`retrieve_heal_experience(pattern)` 命中历史成功策略时提示，未知失败可映射到已成功策略。
- 配置：settings `RAG_CONFIG`（enabled/mode/collections/score_threshold/embedder…）；
  `.env.example` 增加 `QDRANT_MODE/QDRANT_LOCAL_PATH/RAG_SCORE_THRESHOLD/RAG_ENABLED/RAG_EMBEDDER/EMBEDDING_*`；
  `.gitignore` 忽略 `.qdrant_local/`。

**验证**：
- `run_agent_demo --goal "用户登录"`：首轮 `[retrieved 0 similar cases]`（建库），次轮
  `[retrieved 3 similar cases]` 并列出历史标题。
- selector 复用：种入 `#phone_v2/#code_v2/#submit_v2` 历史用例后生成 steps 复用该组 selector。
- 自愈：`--execute --self-heal --inject-failure selector` 第 2 轮输出
  `[retrieved 2 similar failures]` 与 `[heal experience] history: element_not_found -> selector_remap (success_rate=0.67)`，rerun=pass。
- 降级：`RAG_ENABLED=0` 与 `QDRANT_MODE=remote`（不可达）均 `[retrieved 0 similar cases]` 且流程正常完成。
- `pytest -q` → 30 passed（新增 13 条 Phase G 单测：embedder/retriever 三方法/降级/planner/fixer/echo few-shot）；
  `manage.py check` → no issues；`makemigrations --check` → no changes（无需迁移）。

**未做**：reranker 精排（仅 score 阈值）、批量 embed 历史数据脚本、embedding 缓存层、混合检索（BM25）。

---

# Phase J — 需求文档（Jira Story）→ 三类用例 → 归档导出（实施计划）

> **目标**：上传 Jira Sprint Story 格式需求文档，AI 生成 **手动用例 / UI 自动化 / 接口自动化**，
> 存档并可导出交付（Excel / pytest 工程 / JSON）。UI 先用本地 fixture，Swagger 仅公开可访问。
> 单人本地先行；服务器 + CICD 放 M3。

## 决策（已确认）

| 项 | 决策 |
|---|---|
| 模型 | DeepSeek V4.1 Flash（low/high），接真实 `call_llm`，去掉无意义的 `NO_LLM` 兜底 |
| 优先级 | 先做需求文档轨道；网站轨道放 M2 |
| 网站 | 内网 + 简单登录认证（M2） |
| API 来源 | 仅 Swagger（公开可访问，token 后续） |
| 产出 | 手动用例 + 自动化用例，DB 存档 + 导出交付 |
| 存储 | 单 `TestCase` + `kind`(manual/automated) + `test_type`(functional/ui/api) |
| 导出 | 手动 Excel(.xlsx)；自动化 pytest 工程 zip + JSON（无额外格式） |
| 手动用例 | 也由 AI 生成；输入模板参考 Jira Sprint Story |
| M1 UI 目标 | 本地 `mcp_servers/fixtures/login.html`；真实站点 M2 |
| 部署 | 单人本地 → M3 服务器 + CICD |

## 需求输入模板（Jira Story + Gherkin）

新增 `templates/requirements/story_template.md`，关键结构：

```markdown
# Epic: <Epic 名>
> UI: <base_url>
> API: <api_base_url>
> Swagger: <swagger_url>

## Sprint: <sprint>
### Story: <KEY-101> <标题>
- 类型: 功能, UI, 接口
- 优先级: P0
- Story Points: 5
- 组件: 登录
- 标签: login, smoke
- 自动化: manual=是, ui=是, api=是
- 关联接口: POST /api/login

**As a** <角色>
**I want** <目标>
**So that** <价值>

**业务规则**
- ...

**测试数据**
- 手机号: 13800138000

**Acceptance Criteria**
```gherkin
Scenario: 正常登录
  Given 用户在登录页
  When 输入手机号 "13800138000" 和验证码 "123456"
  And 点击登录按钮
  Then 页面提示 "登录成功"
```

**Definition of Done**
- [ ] 接口返回 200
```

映射：Gherkin `Given/When/Then` → 手动用例步骤/预期 + UI 自动化 steps/assertions；
`关联接口` + Swagger → API 自动化；`自动化` 行控制产出形态。

## M1 链路

```
上传 Story 模板文档
 → story_parser 解析（Story/Gherkin/元数据）→ Scenario 落库
 → LLM 生成：① 手动用例 ② UI 自动化 ③ API 自动化（读 Swagger）
 → 本地 fixture 执行 UI + Mock API 执行 API
 → 失败自愈（规则 → LLM 候选）
 → 存档：DB + Excel(手动) + pytest 工程(自动化) + JSON
```

## Step 1–7

| Step | 内容 | 关键触点 |
|---|---|---|
| **1 模板与解析** | Story 模板 + `story_parser.py`（Gherkin/元数据）+ `Scenario` 模型 | `templates/requirements/`、`core/parsers/`、`core/models.py`、`core/services/doc_service.py` |
| **2 真实 LLM 生成** | `call_llm` 接入 graph；pydantic schema + prompts；去重；`LLMCall` 成本入库；`llm_smoke` | `agent/llm.py`、`agent/graph.py`、`agent/schemas.py`、`agent/prompts/` |
| **3 Swagger 接口用例** | 公开 spec 拉取 → endpoint → 正/负/边界 API 场景；JSON Schema 断言 | `core/parsers/openapi_parser.py`、`api_server.py` |
| **4 UI 生成 + 本地执行** | Gherkin→UI steps；弹性定位器；playwright 动作扩展 + 失败截图 | `agent/prompts/ui_cases.md`、`mcp_servers/playwright_server.py`、`executor/executor.py` |
| **5 归档 + 导出** | `kind/test_type/scenario FK/manual_steps`；`ExportJob`；`export_cases` 命令；Web 导出按钮 | `core/models.py`、`core/services/export_service.py`、`core/management/commands/export_cases.py` |
| **6 自愈（UI+API）** | 规则 + LLM 候选 + 向量定位器库；API 期望值/token 自愈 | `selfheal/`、`rag/` |
| **7 Web 最小审核** | Scenario 审核、用例分栏、运行、导出 | `core/views.py`、`templates/core/` |

**清理项**：`graph.py` 移除 echo 兜底路径；`echo_server.py` 与 `tests/test_rag_phase_g.py::TestEchoFewShot` 移除（few-shot 改由真实示例注入）。

## 数据模型

| 模型 | 变更 |
|---|---|
| `Scenario`（新） | doc/project FK、story_key、epic、sprint、module、title、test_types、priority、story_points、role/goal/benefit、business_rules、test_data、acceptance(Gherkin)、automation、api_ref、tags、raw_text |
| `TestCase` | + kind、test_type、module、scenario FK、manual_steps、expected_result |
| `TestGenerationBatch` | + manual_count、automated_count |
| `ExportJob`（新） | batch/project、format、status、file、created_at |
| `LLMCall`（新） | task/model/tokens/cost/latency |

新增依赖：`openpyxl`（导出）、`jsonschema`（API 断言）。

## 验证基线

- `cd platform && python -m pytest ../tests/ -q` 不回归（新增 parser/schema/export 单测）。
- `python manage.py check` 无错、`makemigrations --check` 无变更。
- `process_doc <id>`：Story → 手动 + UI + API 用例 → 执行 → 自愈 → 三种导出。

## M2 / M3

- **M2 内网站点**：`site_explorer_server`（爬取 + 页面模型）+ 简单登录认证（`storage_state`），真实站点替换本地 fixture。约 10–14 人日。
- **M3 服务器 + CICD**：Celery/Redis、SSE 进度、定时回归、GitHub Actions/JUnit 导出、通知、多人权限。约 15–20 人日。
- **延后**：Swagger 鉴权 token、Postman、PDF/DOCX/Confluence、reranker、截图录像、多租户。

## Phase J 实施进展

### Step 1 ✅（完成）
- `templates/requirements/story_template.md`（Jira Story + Gherkin 模板）、`tests/fixtures/story_requirements.md`。
- `apps/core/parsers/story_parser.py`（Epic/Sprint/Story、As a/I want/So that、业务规则、测试数据、Gherkin AC、DoD、automation、api_ref、env）；`parser_factory` 按文本特征选 StoryParser。
- `Scenario` 模型 + 迁移 `core.0003` + admin；`doc_service` 幂等重建 Scenario。
- 验证：解析 2 Story（ACC-101/102）；`process_doc` 解析→生成→执行串联；`pytest` 53 passed。

### Step 2 ✅（完成）
- `apps/agent/schemas.py`：`ManualCase/UICase/ApiCase` 三类 pydantic schema。
- `apps/agent/prompts/`：手动/UI/接口提示词（注入 Story + Gherkin + 测试数据 + API/UI 地址）。
- `apps/agent/generation.py`：`call_structured`（JSON 提取 + pydantic 校验 + 一次修复）、`generate_for_scenario`（按 automation 生成三类）、去重、`LLMCall` 成本记录。
- `apps/agent/graph.py::generator_node` 改为 LLM 生成（移除 echo 兜底）；`_save_test_cases` 写入 `kind/test_type/module/scenario/manual_steps/expected_result`。
- `TestCase` 新增字段 + 迁移 `testcases.0005`；`LLMCall` + 迁移 `core.0004`；admin 注册。
- `generation_service` 改用 `Scenario` 行并注入 `scenario_id`；自动执行仅取自动化用例。
- `manage.py llm_smoke`：真实 DeepSeek Flash 调用 + 结构化输出验证。
- **关键修复**：DeepSeek Flash 默认 thinking 会耗尽 `max_tokens` 导致 content 为空 → low 档 `thinking=disabled`、high 档 `thinking=enabled` + `reasoning_effort`；`status_equals` 断言 int/str 兼容。
- `executor` 跳过手动用例；`mock_api.py` 实现登录业务规则（空值/格式/错误码）。
- 验证：Story 文档 → 37 用例（22 手动 / 2 UI / 13 接口），`LLMCall` 12 条（成本入库，约 $0.01）；`pytest` 68 passed；`process_doc` 6/15 自动化通过（其余为 mock 与 LLM 期望差异，待 Step 3 Swagger / Step 4 页面上下文提升）。
### Step 3 ✅（完成）
- `apps/core/parsers/openapi_parser.py`：`fetch_spec`（公开 spec，JSON/YAML）、`resolve_refs`（`$ref`）、`parse_endpoints`、`endpoints_to_scenarios`（每 endpoint 生成 正常 / 缺参异常 / 边界 场景；断言 `status_equals` + `json_schema` + `json_field`；请求体从 schema 示例生成）。
- `apps/core/services/swagger_service.py`：`import_swagger_for_doc` 拉取 → 落库 `Scenario(source=swagger)`（best-effort，失败不阻断）。
- `Scenario` 新增 `api_spec` / `source`（迁移 `core.0005`）。
- 生成：`generation._api_cases_from_spec` 对 Swagger 场景确定性生成接口用例（不调 LLM）；executor 新增 `json_schema` 断言（jsonschema）。
- `process_doc`：自动识别 `project.swagger_url` / 场景 `env.swagger`；离线演示时 mock 同时提供 `/v3/api-docs` 公开 spec。
- `mock_api` 支持 /login、/health、/v3/api-docs。
- 验证：`openapi_sample.json` → 4 个接口场景；`process_doc` 批次 #7：total=6 场景（2 Story + 4 Swagger），生成 38 用例，Swagger 用例 **4/4 通过**（含 json_schema）；`pytest` 76 passed。

### Step 4 ✅（完成，含 RAG 接入）
- **RAG 接入生成**：`planner_node` 增加 `aretrieve_knowledge`（Phase G retriever，collection `test_knowledge`，本地/远端自动降级）并返回 `retrieved_knowledge`；`generator_node` 把 `retrieved_cases`（历史相似用例 few-shot）+ `retrieved_knowledge`（PRD/接口规范）注入 manual/UI/API 三类 prompt；空库/不可用返回 []，不阻断。
- **页面感知 UI 生成**：`generation.fetch_page_snapshot` 用 Playwright MCP 打开目标页抓取元素（id/name/placeholder/label/text）注入 UI prompt；LLM 产出弹性定位器（`#phone`、`button:has-text("登录")`、`text="登录成功"`）。
- **执行能力扩展**：`playwright_server` 新增 `select/check/hover/press/wait_for/screenshot`；`executor._run_steps` 支持 `select/check/hover/press/wait_for`，失败步骤自动截图并写入 `TestStepResult.screenshot_path`。
- 验证：`process_doc 4` 批次 #8 → 14/15 自动化通过；UI 2/2、Swagger 4/4；`pytest` 84 passed；`manage.py check` 无错。
- 说明：RAG 默认仍为 `FakeEmbedder`（dim=8）；`RAG_EMBEDDER=bge` + embedding 服务可切真实语义；`RAG_ENABLED=0` 降级。知识库需先入库 `test_knowledge` 才会命中。

### Step 5 ✅（完成）
- `TestGenerationBatch` 新增 `manual_count` / `automated_count`（迁移 `core.0006`）；生成后回写。
- 新增 `ExportJob` 模型（迁移 `core.0006`）+ admin。
- `apps/core/services/export_service.py`：
  - `xlsx` 手动用例 Excel（openpyxl；用例ID/模块/标题/类型/优先级/前置条件/步骤/预期/标签）。
  - `pytest` 自动化工程 zip（`conftest.py` + `test_ui_generated.py`(Playwright) + `test_api_generated.py`(httpx+jsonschema) + requirements/README/manifest）。
  - `json` 全量存档（批次 + 用例）。
- `manage.py export_cases <batch_id> [--format xlsx|pytest|json|all]`。
- Web：批次页新增导出按钮；`/batches/<id>/export/<fmt>/` 直接下载。
- 依赖：`openpyxl`、`jsonschema` 写入 pyproject。
- 验证：`export_cases 8` 三种格式产物生成；导出 pytest 工程 `py_compile` 通过；Web 导出端点 200/404 正常；`pytest` 91 passed。

### Step 6 ✅（完成）
- **向量定位器库**：`rag.retriever` 新增 `COLLECTION_LOCATORS` + `retrieve_locator`；`rag.indexer.index_locator` 记录成功的 selector 修复；fixer 在规则模糊匹配失败后先查向量库。
- **LLM selector 候选**：`fixer._llm_selector_fix` 抓取目标页元素候选，经 `self_heal_repair`（high）→ `refine_locator`（low 兜底）提出新 selector，并**校验候选必须存在于页面元素**后应用、回写向量库。
- **API 断言自愈**：按 `TestCase.test_type == api` 走独立分支 `_fix_api_assertion`：
  - `json_field/json_contains` 值漂移 → 刷新 expected（`assertion_refresh`）；
  - `json_path_exists` 字段重命名 → 模糊匹配 body 键名修正 path（`field_rename`）。
  - executor 失败断言写入 `path`（selector）与响应体，供自愈定位。
- **指标**：`manage.py heal_stats` 打印 (失败模式→策略) 成功率。
- 验证：脚本 → UI `#code_old`→`#code`（selector_remap，healed）、API `json_field` expected `1`→`0`（assertion_refresh，rerun pass）；`locator_history` 写入并检索命中（score 0.77）；`SelfHealLog` 增长；`pytest` 103 passed。

### 未完成
- Phase J Step 7 审核界面（Scenario 审核/编辑、用例分栏、触发运行）。
