"""
Git MCP Server (stdio)

提供工具：
- create_pull_request:  自动创建 PR (自愈修复后)
- commit_changes:       提交变更
- create_branch:        创建分支

自愈闭环的最后一步：定位器修复 → 验证通过 → 自动开 PR
"""
import asyncio
import json
import subprocess
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


server = Server("git-ops")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_branch",
            description="创建并切换到新分支",
            input_schema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string"},
                    "base": {"type": "string", "default": "main"},
                },
                "required": ["branch"],
            },
        ),
        Tool(
            name="commit_changes",
            description="提交文件变更",
            input_schema={
                "type": "object",
                "properties": {
                    "files": {"type": "object", "description": "{"path": "content"}"},
                    "message": {"type": "string"},
                },
                "required": ["files", "message"],
            },
        ),
        Tool(
            name="create_pull_request",
            description="创建 Pull Request (支持 GitHub/GitLab API)",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "branch": {"type": "string"},
                    "base": {"type": "string", "default": "main"},
                    "provider": {"type": "string", "enum": ["github", "gitlab"], "default": "github"},
                },
                "required": ["title", "branch"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "create_branch":
        return await _create_branch(arguments)
    elif name == "commit_changes":
        return await _commit_changes(arguments)
    elif name == "create_pull_request":
        return await _create_pr(arguments)
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _create_branch(args: dict) -> list[TextContent]:
    branch = args["branch"]
    base = args.get("base", "main")
    subprocess.run(["git", "checkout", "-b", branch, base], check=True)
    return [TextContent(type="text", text=json.dumps({"created": branch}))]


async def _commit_changes(args: dict) -> list[TextContent]:
    """写入文件并提交"""
    files = args["files"]
    message = args["message"]

    # 写入文件
    for path, content in files.items():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    # git add + commit
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)

    return [TextContent(type="text", text=json.dumps({"committed": message}))]


async def _create_pr(args: dict) -> list[TextContent]:
    """
    创建 PR (GitHub 示例，GitLab 类似)
    优先使用 gh CLI，否则用 API
    """
    provider = args.get("provider", "github")
    title = args["title"]
    body = args.get("body", "")
    branch = args["branch"]
    base = args.get("base", "main")

    if provider == "github":
        # 尝试 gh CLI
        try:
            result = subprocess.run(
                ["gh", "pr", "create", "--title", title, "--body", body,
                 "--head", branch, "--base", base],
                capture_output=True, text=True, check=True,
            )
            return [TextContent(type="text", text=json.dumps({
                "url": result.stdout.strip(),
                "provider": "github",
            }))]
        except (subprocess.CalledProcessError, FileNotFoundError):
            # 降级为 API 调用
            return await _create_pr_api(args)

    return [TextContent(type="text", text=json.dumps({"status": "pending_manual"}))]


async def _create_pr_api(args: dict) -> list[TextContent]:
    """通过 GitHub API 创建 PR"""
    import httpx
    import os

    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")  # e.g. "owner/repo"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{repo}/pulls",
            json={
                "title": args["title"],
                "body": args.get("body", ""),
                "head": args["branch"],
                "base": args.get("base", "main"),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()

    return [TextContent(type="text", text=json.dumps({
        "url": data.get("html_url"),
        "number": data.get("number"),
    }, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
