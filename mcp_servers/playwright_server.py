"""
Playwright MCP Server (stdio)

真浏览器执行（headless Chromium），供 executor 按步骤驱动：
- navigate:        打开 URL
- click:           点击元素
- fill:            填写输入框
- snapshot:        获取页面文本/标题/交互元素
- assert_text:     断言元素文本（contains/equals）
- assert_visible:  断言元素可见
- get_locator:     推荐定位器（供自愈定位器库）
- run_tests:       执行 pytest 文件（保留的批量执行入口）

设计原则：基于 accessibility/DOM 文本，无需视觉模型。
浏览器未安装时返回 {"error": ...}，不阻断调用方。
"""
import asyncio
import json as _json
import os
import sys
from pathlib import Path

from mcp.server import MCPServer

mcp = MCPServer("playwright-test")


# ============================================================
# 浏览器会话（懒加载，MCP server 进程内复用）
# ============================================================
_state: dict = {"pw": None, "browser": None, "page": None}


async def _get_page():
    if _state["page"] is not None:
        return _state["page"]

    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
    except Exception as exc:  # 浏览器未安装等
        await pw.stop()
        raise RuntimeError(
            f"Playwright browser unavailable: {exc}. "
            "提示: 执行 `playwright install chromium` 后重试（当前不阻断调用方）。"
        )
    _state["pw"] = pw
    _state["browser"] = browser
    page = await browser.new_page()
    # 短超时，便于自愈快速拿到失败特征（自愈会插入 wait 补偿）
    page.set_default_timeout(1000)
    page.set_default_navigation_timeout(5000)
    _state["page"] = page
    return page


async def _close_browser() -> None:
    page = _state.get("page")
    browser = _state.get("browser")
    pw = _state.get("pw")
    if page is not None:
        await page.close()
    if browser is not None:
        await browser.close()
    if pw is not None:
        await pw.stop()
    _state.update({"pw": None, "browser": None, "page": None})


def _ok(data: dict) -> str:
    return _json.dumps(data, ensure_ascii=False)


def _err(exc: Exception) -> str:
    return _json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)


# ============================================================
# 工具定义
# ============================================================
@mcp.tool(name="navigate", description="打开指定 URL，返回标题与地址")
async def navigate(url: str) -> str:
    try:
        page = await _get_page()
        resp = await page.goto(url, wait_until="domcontentloaded")
        return _ok({
            "url": page.url,
            "title": await page.title(),
            "status": resp.status if resp else None,
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool(name="click", description="点击指定 selector 的元素")
async def click(selector: str) -> str:
    try:
        page = await _get_page()
        await page.click(selector)
        return _ok({"clicked": selector})
    except Exception as exc:
        return _err(exc)


@mcp.tool(name="fill", description="在指定 selector 的输入框填写 value")
async def fill(selector: str, value: str) -> str:
    try:
        page = await _get_page()
        await page.fill(selector, value)
        return _ok({"filled": selector, "value": value})
    except Exception as exc:
        return _err(exc)


@mcp.tool(name="snapshot", description="获取当前页面文本、标题与交互元素")
async def snapshot() -> str:
    try:
        page = await _get_page()
        elements = await page.evaluate(
            """() => Array.from(document.querySelectorAll('input,button,a,select,textarea'))
                .map(el => {
                    let label = '';
                    if (el.labels && el.labels.length) {
                        label = Array.from(el.labels).map(l => l.innerText).join(' ');
                    } else if (el.id) {
                        const l = document.querySelector('label[for="' + el.id + '"]');
                        if (l) label = l.innerText;
                    }
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || null,
                        name: el.getAttribute('name'),
                        placeholder: el.getAttribute('placeholder'),
                        ariaLabel: el.getAttribute('aria-label'),
                        text: (el.innerText || el.value || '').slice(0, 80),
                        label: label.slice(0, 80),
                    };
                })"""
        )
        return _ok({
            "url": page.url,
            "title": await page.title(),
            "text": (await page.inner_text("body")).strip(),
            "elements": elements,
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool(name="get_text", description="获取指定 selector 元素当前文本")
async def get_text(selector: str) -> str:
    try:
        page = await _get_page()
        text = (await page.inner_text(selector)).strip()
        return _ok({"selector": selector, "text": text})
    except Exception as exc:
        return _err(exc)


@mcp.tool(name="assert_text", description="断言元素文本 (mode: contains|equals)")
async def assert_text(selector: str, expected: str, mode: str = "contains") -> str:
    try:
        page = await _get_page()
        actual = (await page.inner_text(selector)).strip()
        if mode == "equals":
            passed = actual == expected
        else:
            passed = expected in actual
        return _ok({
            "passed": passed,
            "selector": selector,
            "expected": expected,
            "actual": actual,
            "mode": mode,
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool(name="assert_visible", description="断言元素可见")
async def assert_visible(selector: str) -> str:
    try:
        page = await _get_page()
        visible = await page.is_visible(selector)
        return _ok({"passed": bool(visible), "selector": selector})
    except Exception as exc:
        return _err(exc)


@mcp.tool(
    name="get_locator",
    description="获取元素的推荐定位器 (供自愈定位器库使用)",
)
async def get_locator(description: str) -> str:
    """
    基于 accessibility/DOM 推荐定位器。
    优先级：role+name > text > CSS > XPath
    """
    candidates = [
        {"strategy": "role", "locator": f"role=button[name='{description}']", "score": 0.95},
        {"strategy": "text", "locator": f"text='{description}'", "score": 0.80},
        {"strategy": "css", "locator": f"[data-testid='{description}']", "score": 0.60},
    ]
    return _json.dumps(candidates, ensure_ascii=False)


@mcp.tool(name="run_tests", description="执行 pytest 测试文件，返回结果")
async def run_tests(
    test_code: str,
    test_file: str,
    browser: str = "chromium",
) -> str:
    Path(test_file).parent.mkdir(parents=True, exist_ok=True)
    with open(test_file, "w") as f:
        f.write(test_code)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent / "platform")

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pytest",
        test_file,
        "-v",
        "--tb=short",
        "--json-report",
        "--json-report-file=/tmp/pytest_report.json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()

    report = {}
    report_path = Path("/tmp/pytest_report.json")
    if report_path.exists():
        with open(report_path) as f:
            report = _json.load(f)

    result = {
        "exit_code": proc.returncode,
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "summary": report.get("summary", {}),
        "tests": [
            {
                "nodeid": t["nodeid"],
                "outcome": t["outcome"],
                "error": t.get("longrepr", ""),
            }
            for t in report.get("tests", [])
        ],
    }

    return _json.dumps(result, indent=2, ensure_ascii=False)


@mcp.tool(name="close", description="关闭浏览器会话")
async def close() -> str:
    try:
        await _close_browser()
        return _ok({"closed": True})
    except Exception as exc:
        return _err(exc)


if __name__ == "__main__":
    mcp.run("stdio")
