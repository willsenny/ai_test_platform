# 登录系统测试需求

本文件用于 Phase I 端到端验证：上传 → 解析 → 批量生成 → 执行 → 自愈。

## 场景一：手机号+验证码登录（正常流程）

用户打开登录页，输入手机号与验证码，点击登录按钮，页面提示登录成功。

优先级：P0
标签：login, smoke

### 验收标准

- 页面显示“登录成功”
- 登录结果区域可见

## 场景二：验证码输入框回归

登录页验证码输入框使用了历史遗留选择器，需要回归验证登录流程仍然可用。

优先级：P1
标签：login, regression

```json
{
  "type": "ui",
  "steps": [
    {"action": "goto", "selector": "", "value": "", "description": "打开登录页"},
    {"action": "fill", "selector": "#phone", "value": "13800138000", "description": "输入手机号"},
    {"action": "fill", "selector": "#code_old", "value": "123456", "description": "输入验证码（遗留选择器）"},
    {"action": "click", "selector": "#submit", "value": "", "description": "点击登录"}
  ],
  "assertions": [
    {"type": "text_contains", "selector": "#result", "expected": "登录成功"}
  ]
}
```

### 验收标准

- 使用历史选择器也能完成登录

## 场景三：登录接口返回码校验

调用登录接口，校验 HTTP 状态码与业务返回码。

优先级：P1
标签：api, login

接口地址：POST /api/login

```json
{
  "type": "api",
  "request": {
    "method": "POST",
    "path": "/api/login",
    "headers": {"Content-Type": "application/json"},
    "body": {"phone": "13800138000", "code": "123456"}
  },
  "assertions": [
    {"type": "status_equals", "expected": 200},
    {"type": "json_field", "path": "code", "expected": 0}
  ]
}
```

### 验收标准

- 接口返回 200
- 业务码 code 为 0
