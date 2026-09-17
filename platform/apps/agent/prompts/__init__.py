"""
生成提示词构建（Phase J Step 2）。

把 Scenario（Jira Story + Gherkin）转成三类生成请求：
- build_manual_prompt → 手动用例
- build_ui_prompt     → UI 自动化（Playwright）
- build_api_prompt    → 接口自动化
"""
import json

MANUAL_SYSTEM = (
    "你是资深测试工程师。根据 Jira Story 与 Gherkin 验收标准，设计可人工执行的功能测试用例。"
    "每个用例包含：标题、前置条件、有序操作步骤（每步含操作与预期）、整体预期结果、优先级(P0/P1/P2)、标签。"
    "覆盖正常流、边界值、异常流。严格输出 JSON，不要多余解释。"
)

UI_SYSTEM = (
    "你是 UI 自动化工程师，负责把测试场景转成 Playwright 步骤。"
    "action 仅可用：goto/navigate、fill、click、wait、select、check、hover、press。"
    "selector 规则：输入框用 [placeholder=\"占位符\"] 或 #id；"
    "点击按钮必须用 button:has-text(\"按钮文本\")，不要用裸 text=文本（会误匹配其它元素）。"
    "断言 type 仅可用：text_contains、text_equals、visible。"
    "断言的 expected 必须来自 Gherkin 的 Then 预期（如“登录成功”“验证码错误”），"
    "并且 assert 的 selector 用 text=\"预期文本\"（带双引号做精确匹配），不要用 body。"
    "严格输出 JSON。"
)

API_SYSTEM = (
    "你是接口测试工程师。根据 Story、关联接口与 Gherkin 预期，生成接口测试用例。"
    "断言 type 仅可用：status_equals、json_field、json_contains、json_path_exists。"
    "结合测试数据生成请求体与参数；覆盖正常、异常与边界。严格输出 JSON。"
)


def scenario_context(scenario: dict) -> str:
    """把场景结构转成可读上下文。"""
    lines = [
        f"Story: {scenario.get('story_key', '')} {scenario.get('title', '')}".strip(),
        f"Epic/模块: {scenario.get('epic', '')} / {scenario.get('module', '')}".strip(),
    ]
    if scenario.get("goal"):
        lines.append(f"目标: {scenario['goal']}")
    if scenario.get("benefit"):
        lines.append(f"价值: {scenario['benefit']}")
    if scenario.get("business_rules"):
        lines.append("业务规则:\n" + "\n".join(f"- {r}" for r in scenario["business_rules"]))
    if scenario.get("test_data"):
        lines.append("测试数据: " + json.dumps(scenario["test_data"], ensure_ascii=False))
    if scenario.get("api_ref"):
        lines.append(f"关联接口: {scenario['api_ref']}")

    acceptance = scenario.get("acceptance") or []
    if acceptance:
        lines.append("验收标准(Gherkin):")
        for item in acceptance:
            lines.append(f"Scenario: {item.get('name', '')}")
            for given in item.get("given", []):
                lines.append(f"  Given {given}")
            for when in item.get("when", []):
                lines.append(f"  When {when}")
            for then in item.get("then", []):
                lines.append(f"  Then {then}")
    elif scenario.get("acceptance_criteria"):
        lines.append("验收标准:")
        lines.extend(f"- {c}" for c in scenario["acceptance_criteria"])
    return "\n".join(lines)


def build_manual_prompt(scenario: dict) -> str:
    return (
        f"{scenario_context(scenario)}\n\n"
        "请为以上 Story 生成手动测试用例，覆盖正常/边界/异常。\n"
        '输出 JSON：{"cases":[{"title","preconditions":[],"steps":[{"action","expected"}],'
        '"expected_result","priority","tags":[]}]}'
    )


def build_ui_prompt(scenario: dict, target_url: str = "") -> str:
    target = target_url or scenario.get("env", {}).get("ui", "")
    return (
        f"{scenario_context(scenario)}\n"
        f"被测 UI 地址: {target}\n\n"
        "请把可自动化的 UI 场景转成 Playwright 步骤。\n"
        '输出 JSON：{"cases":[{"title","preconditions":[],"steps":[{"action","selector","value","description"}],'
        '"assertions":[{"type","selector","expected"}],"priority","tags":[],"target_url"}]}'
    )


def build_api_prompt(scenario: dict, api_base_url: str = "") -> str:
    base = api_base_url or scenario.get("env", {}).get("api", "")
    return (
        f"{scenario_context(scenario)}\n"
        f"API 根地址: {base}\n\n"
        "请生成接口测试用例（正常/异常/边界），请求体参考测试数据。\n"
        '输出 JSON：{"cases":[{"title","method","path","headers":{},"body":{},"params":{},'
        '"assertions":[{"type","path","expected"}],"priority","tags":[]}]}'
    )
