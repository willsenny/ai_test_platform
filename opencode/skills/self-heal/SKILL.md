---
name: self-heal
description: |
  自愈引擎：失败用例 → 五段闭环 → 自动开 PR
  这是平台的核心差异化能力。
version: 1.0.0
triggers:
  - "自愈"
  - "修复测试"
  - "self heal"
  - "heal"
---

# Self-Heal Skill

## 五段闭环

```
1. 规则修复 (Flash low)
   - TimeoutError → wait_for_visible
   - ElementNotVisible → scrollIntoView
   - NetworkError → 幂等重试
   - StaleElement → 重新查询

2. 向量定位器库 (Flash low)
   - 从 Qdrant 检索历史成功定位器
   - 相同 URL + 相似元素描述 → 推荐

3. LLM 候选 (Flash high)
   - 输入: 失败日志 + 截图 + accessibility tree
   - 输出: 候选定位器 + 置信度

4. 重跑验证 (MCP)
   - Playwright MCP 跑单个用例
   - 成功 → 进入 Step 5
   - 失败 → 回到 Step 1 (下一轮)

5. 开 PR (Git MCP)
   - 写入 tests/locators/{test_id}.py
   - git checkout -b self-heal/{test_id}
   - commit + push + 创建 PR
```

## 成本保护

- `retry_budget` 默认 3，超过立即放弃
- 仅 Step 3 使用 reasoning=high，其余走 low
- 单次自愈成本约 $0.003–$0.05

## 输入

- `test_id`: 测试用例 ID
- `error_message`: 错误信息
- `stack_trace`: 堆栈
- `screenshot_path`: 截图路径 (可选)
- `page_url`: 页面 URL
- `locator`: 失败的定位器

## 输出

```json
{
  "success": true,
  "strategy": "vector",
  "old_locator": "#old",
  "new_locator": "#new",
  "confidence": 0.92,
  "retries": 1,
  "pr_url": "https://github.com/.../pull/123"
}
```
