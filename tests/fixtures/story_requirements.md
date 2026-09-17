# Epic: 用户账户体系

> UI: http://localhost:8000
> API: http://localhost:8000/api
> Swagger: http://localhost:8000/v3/api-docs

## Sprint: 2026-S1

### Story: ACC-101 手机号验证码登录

- 类型: 功能, UI, 接口
- 优先级: P0
- Story Points: 5
- 组件: 登录
- 标签: login, smoke
- 自动化: manual=是, ui=是, api=是
- 关联接口: POST /api/login

**As a** 已注册用户
**I want** 使用手机号+验证码登录
**So that** 我可以访问个人中心

**业务规则**

- 验证码 5 分钟有效
- 连续错误 5 次锁定 10 分钟

**测试数据**

- 手机号: 13800138000
- 验证码: 123456

**Acceptance Criteria**

```gherkin
Scenario: 正常登录
  Given 用户在登录页
  When 输入手机号 "13800138000" 和验证码 "123456"
  And 点击登录按钮
  Then 页面提示 "登录成功"

Scenario: 验证码错误
  Given 用户在登录页
  When 输入手机号 "13800138000" 和验证码 "000000"
  And 点击登录按钮
  Then 页面提示 "验证码错误"
```

**Definition of Done**

- [ ] 接口返回 200
- [ ] 登录成功后可访问首页

### Story: ACC-102 连续错误锁定账户

- 类型: 功能
- 优先级: P1
- Story Points: 3
- 组件: 登录
- 标签: login, security
- 自动化: manual=是, ui=否, api=否
- 关联接口: 无

**As a** 系统管理员
**I want** 在用户连续输错验证码 5 次后锁定账户
**So that** 防止暴力破解

**业务规则**

- 连续错误 5 次锁定 10 分钟

**测试数据**

- 手机号: 13800138000
- 错误验证码: 000000
- 错误次数: 5

**Acceptance Criteria**

```gherkin
Scenario: 连续错误锁定
  Given 用户已连续输错验证码 4 次
  When 第 5 次输入错误验证码
  Then 账户被锁定 10 分钟
  And 页面提示 "账户已锁定"
```

**Definition of Done**

- [ ] 锁定期间正确验证码也无法登录
