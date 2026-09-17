# Epic: <Epic 名称>

> UI: <被测 Web 地址，如 http://localhost:8000>
> API: <被测 API 根地址，如 http://localhost:8000/api>
> Swagger: <OpenAPI spec 地址，仅支持公开可访问>

## Sprint: <Sprint 名称，如 2026-S1>

### Story: <KEY-101> <Story 标题>

- 类型: 功能, UI, 接口
- 优先级: P0
- Story Points: 5
- 组件: <组件名>
- 标签: <tag1, tag2>
- 自动化: manual=是, ui=是, api=是
- 关联接口: <METHOD /path，如 POST /api/login>

**As a** <角色>
**I want** <想要达成的目标>
**So that** <带来的价值>

**业务规则**

- <规则 1>
- <规则 2>

**测试数据**

- <字段名>: <值>
- <字段名>: <值>

**Acceptance Criteria**

```gherkin
Scenario: <场景名称>
  Given <前置条件>
  When <操作>
  And <操作>
  Then <预期结果>

Scenario: <异常场景名称>
  Given <前置条件>
  When <操作>
  Then <预期结果>
```

**Definition of Done**

- [ ] <完成标准 1>
- [ ] <完成标准 2>

---

### Story: <KEY-102> <Story 标题>

- 类型: 功能
- 优先级: P1
- Story Points: 3
- 组件: <组件名>
- 标签: <tag1>
- 自动化: manual=是, ui=否, api=否
- 关联接口: 无

**As a** <角色>
**I want** <目标>
**So that** <价值>

**业务规则**

- <规则>

**测试数据**

- <字段名>: <值>

**Acceptance Criteria**

```gherkin
Scenario: <场景名称>
  Given <前置条件>
  When <操作>
  Then <预期结果>
```

**Definition of Done**

- [ ] <完成标准>
