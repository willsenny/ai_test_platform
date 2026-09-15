---
name: test-generator
description: |
  从自然语言需求生成完整测试用例（LangGraph 编排 + RAG 增强）
  支持：功能测试、接口测试、UI 测试
version: 1.0.0
triggers:
  - "生成测试用例"
  - "写测试"
  - "test case"
  - "testcase"
---

# Test Generator Skill

## 输入

- `requirement` (str): 自然语言需求描述
- `project_id` (str, optional): 项目 ID（用于 RAG 隔离）
- `doc_type` (str, optional): 限定检索的文档类型

## 流程

```
1. RAG 检索 → 相关 PRD / 接口规范 / 历史用例 / 业务规则
2. LangGraph 编排：
   understand → design_scenarios → generate_steps
   → generate_assertions → generate_api_code → generate_ui_code
3. 执行（MCP: Playwright / API）
4. 自愈（失败 → SelfHealEngine）
```

## 输出

- 结构化测试用例（JSON）
- pytest 接口测试代码
- Playwright UI 测试代码
- 执行报告

## 模型

- 唯一模型: DeepSeek V4.1 Flash (Flash-Only)
- 快速生成: reasoning=low（用例/步骤/断言）
- 深度思考: reasoning=high（需求理解/复杂编排）

## 示例

```
用户输入: "用户登录功能，支持手机号+验证码"
→ 检索 RAG: 登录接口规范、历史登录用例
→ 生成:
  - 正向: 正确手机号+正确验证码 → 登录成功
  - 边界: 验证码过期 (5分钟)
  - 异常: 错误验证码、频繁请求限流
→ 生成 pytest + Playwright 代码
→ 执行 & 报告
```
