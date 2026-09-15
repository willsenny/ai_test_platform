"""
Git MCP Server (stdio)

提供工具：
- create_branch:        创建分支
- commit_changes:       提交变更
- create_pull_request:  自动创建 PR (自愈修复后)

自愈闭环的最后一步：定位器修复 → 验证通过 → 自动开 PR
"""
import json as _json
import os
import subprocess
from pathlib import Path

from mcp.server import MCPServer

mcp = MCPServer("git-ops")


# ============================================================
# 工具定义
# ============================================================
@mcp.tool(name="create_branch", description="创建并切换到新分支")
async def create_branch(branch: str, base: str = "main") -> str:
    subprocess.run(["git", "checkout", "-b", branch, base], check=True)
    return _json.dumps({"created": branch})


@mcp.tool(name="commit_changes", description="提交文件变更")
async def commit_changes(files: dict, message: str) -> str:
    for path, content in files.items():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)

    return _json.dumps({"committed": message})


@mcp.tool(
    name="create_pull_request",
    description="创建 Pull Request (支持 GitHub/GitLab API)",
)
async def create_pull_request(
    title: str,
    branch: str,
    body: str = "",
    base: str = "main",
    provider: str = "github",
) -> str:
    if provider == "github":
        try:
            result = subprocess.run(
                ["gh", "pr", "create", "--title", title, "--body", body,
                 "--head", branch, "--base", base],
                capture_output=True, text=True, check=True,
            )
            return _json.dumps({
                "url": result.stdout.strip(),
                "provider": "github",
            })
        except (subprocess.CalledProcessError, FileNotFoundError):
            return await _create_pr_api(title, body, branch, base)

    return _json.dumps({"status": "pending_manual"})


async def _create_pr_api(title: str, body: str, branch: str, base: str) -> str:
    """通过 GitHub API 创建 PR"""
    import httpx

    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")  # e.g. "owner/repo"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": branch,
                "base": base,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()

    return _json.dumps({
        "url": data.get("html_url"),
        "number": data.get("number"),
    }, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run("stdio")
