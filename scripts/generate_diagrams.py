"""
生成架构图 + 成本对比图
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.family"] = "WenQuanYi Micro Hei"
plt.rcParams["axes.unicode_minus"] = False


def draw_architecture():
    """整体架构图"""
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 12)
    ax.axis("off")
    ax.set_title("AI 测试管理平台 - 整体架构\n(WHartTest + OpenCode + LangGraph + RAG + MCP)",
                 fontsize=14, fontweight="bold", pad=20)

    # 颜色方案
    colors = {
        "front": "#4A90D9",
        "platform": "#5DADE2",
        "agent": "#F39C12",
        "rag": "#27AE60",
        "mcp": "#E74C3C",
        "heal": "#9B59B6",
        "exec": "#1ABC9C",
    }

    def box(x, y, w, h, text, color, fontsize=9):
        rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1",
                              facecolor=color, edgecolor="white", linewidth=1.5, alpha=0.85)
        ax.add_patch(rect)
        ax.text(x + w/2, y + h/2, text, ha="center", va="center",
                fontsize=fontsize, color="white", fontweight="bold")

    def arrow(x1, y1, x2, y2, text="", color="#555"):
        a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="->", mutation_scale=15,
                             color=color, linewidth=1.5)
        ax.add_patch(a)
        if text:
            mx, my = (x1+x2)/2, (y1+y2)/2
            ax.text(mx, my + 0.2, text, fontsize=7, ha="center", color=color, style="italic")

    # === Layer 1: 前端 ===
    box(0.5, 10.5, 15, 1, "前端 (Vue, 沿用 WHartTest 项目管理/用例库/报表)", colors["front"], 10)

    # === Layer 2: Django Monorepo ===
    box(0.5, 8.5, 15, 1.5, "", colors["platform"], 8)
    ax.text(1.2, 9.75, "Django Monorepo (WHartTest 底座, MIT, 直接扩充)", fontsize=9, color="white", fontweight="bold")
    box(1, 8.7, 2.5, 0.5, "项目管理\n(复用)", colors["platform"], 7)
    box(4, 8.7, 2.5, 0.5, "用例库\n(复用+扩充)", colors["platform"], 7)
    box(7, 8.7, 2.5, 0.5, "RAG\nQdrant+Reranker", colors["rag"], 7)
    box(10, 8.7, 2, 0.5, "执行器\n(Actuator)", colors["exec"], 7)
    box(12.5, 8.7, 2.8, 0.5, "自愈引擎\n(核心差异化)", colors["heal"], 7)

    arrow(8, 10.5, 8, 10, "DRF API")

    # === Layer 3: LangGraph Agent ===
    box(0.5, 5.5, 9, 2.5, "", colors["agent"], 8)
    ax.text(5, 7.7, "LangGraph 编排 (需求→场景→步骤→断言→代码→执行→自愈)", fontsize=9, color="white", fontweight="bold")

    nodes = [
        (1, 6.5, "①检索\nRAG", 7),
        (3, 6.5, "②理解\nL2 Pro", 7),
        (5, 6.5, "③场景\nL1 Flash", 7),
        (7, 6.5, "④步骤\nL1 Flash", 7),
        (1, 5.8, "⑤断言\nL1 Flash", 7),
        (3, 5.8, "⑥API代码\nL2 Pro", 7),
        (5, 5.8, "⑦UI代码\nL2 Pro", 7),
        (7, 5.8, "⑧执行\nMCP", 7),
    ]
    for x, y, text, fs in nodes:
        box(x, y, 1.7, 0.5, text, colors["agent"], fs)

    # 自愈循环
    box(10.5, 6, 4.5, 1.5, "", colors["heal"], 8)
    ax.text(12.75, 7.1, "⑨ 自愈五段闭环", fontsize=8, color="white", fontweight="bold")
    ax.text(12.75, 6.5, "规则→向量→LLM→验证→PR", fontsize=7, color="white")

    arrow(9, 7, 10.5, 7, "失败?")
    arrow(12.75, 6, 5, 6, "修复后重跑", "#9B59B6")

    arrow(8, 8.5, 5, 8)

    # === Layer 4: MCP Tool Layer ===
    box(0.5, 3, 15, 2, "", colors["mcp"], 8)
    ax.text(8, 4.7, "MCP Tool Layer (stdio + SSE)", fontsize=10, color="white", fontweight="bold")

    mcp_tools = [
        ("Playwright MCP\n(stdio, 官方)", 1.2),
        ("API MCP\n(httpx+pytest)", 4.2),
        ("DB MCP\n(数据断言)", 7.2),
        ("Git MCP\n(自愈开PR)", 10.2),
        ("WHartTest MCP\n(SSE, 兼容)", 13.2),
    ]
    for text, x in mcp_tools:
        box(x, 3.2, 2.5, 1, text, colors["mcp"], 7)

    arrow(5, 5.5, 5, 5, "MCP 调用")
    arrow(12.75, 6, 12, 4)

    # === Layer 5: 基础设施 ===
    infra = ["Qdrant\n(向量)", "PostgreSQL\n(元数据)", "Redis\n(队列)", "DeepSeek API\n(模型)"]
    for i, text in enumerate(infra):
        box(1 + i * 3.8, 0.8, 2.8, 1, text, "#7F8C8D", 7)

    for x in [2, 5.8, 9.6, 13.4]:
        arrow(x, 3, x, 1.8)

    # 模型标注
    ax.text(14.5, 11.5, "模型路由:\nL1 Flash (70%)\nL2 Pro (25%)\nL3 Sonnet (5%)",
            fontsize=8, ha="right", color="#333",
            bbox=dict(boxstyle="round", facecolor="#FFF9C4", alpha=0.8))

    plt.tight_layout()
    plt.savefig("/data/workspace/ai_test_platform/architecture.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✅ architecture.png")


def draw_cost_comparison():
    """成本对比图"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # --- 左图: 各方案单次生成成本 ---
    ax = axes[0]
    models = ["纯 Sonnet\n4.6", "混合\nL2+L3", "推荐路由\nL1+L2+L3", "纯 Flash\n/Pro"]
    costs = [50, 18, 8, 3]
    colors = ["#E74C3C", "#F39C12", "#27AE60", "#3498DB"]

    bars = ax.bar(models, costs, color=colors, width=0.6)
    ax.set_ylabel("成本 ($/千次生成)", fontsize=11)
    ax.set_title("中型冲刺成本对比\n(100 需求 × 8 用例 + 平台 CRUD)", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 60)

    for bar, cost in zip(bars, costs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"${cost}", ha="center", fontsize=11, fontweight="bold")

    # 省钱标注
    ax.annotate("省 84%", xy=(2, 8), xytext=(2, 35),
                fontsize=11, color="#27AE60", fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="#27AE60"))

    # --- 右图: 模型调用占比 ---
    ax2 = axes[1]
    tiers = ["L1 Flash\n(批量生成)", "L2 Pro\n(复杂编排)", "L3 Sonnet\n(自愈/评审)"]
    shares = [70, 25, 5]
    colors_pie = ["#3498DB", "#F39C12", "#E74C3C"]

    wedges, texts, autotexts = ax2.pie(
        shares, labels=tiers, colors=colors_pie, autopct="%1.0f%%",
        startangle=90, textprops={"fontsize": 9},
    )
    for t in autotexts:
        t.set_fontsize(12)
        t.set_fontweight("bold")
    ax2.set_title("模型调用占比\n(决定成本的关键)", fontsize=11, fontweight="bold")

    plt.tight_layout()
    plt.savefig("/data/workspace/ai_test_platform/cost_comparison.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✅ cost_comparison.png")


def draw_self_heal_flow():
    """自愈五段闭环图"""
    fig, ax = plt.subplots(1, 1, figsize=(14, 5))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 5)
    ax.axis("off")
    ax.set_title("自愈引擎 - 五段闭环 (Self-Heal Engine)", fontsize=13, fontweight="bold", pad=15)

    steps = [
        ("① 规则修复", "L1 Flash\n超时/可见性/网络", "#3498DB"),
        ("② 向量定位器", "L1 Flash\n历史相似定位器", "#2ECC71"),
        ("③ LLM 候选", "L3 Sonnet\n分析截图+日志", "#E74C3C"),
        ("④ 重跑验证", "MCP\nPlaywright 执行", "#F39C12"),
        ("⑤ 开 PR", "Git MCP\n自动提交修复", "#9B59B6"),
    ]

    box_w = 2.2
    gap = 0.4
    start_x = 0.5

    for i, (title, desc, color) in enumerate(steps):
        x = start_x + i * (box_w + gap)
        rect = FancyBboxPatch((x, 1.5), box_w, 2, boxstyle="round,pad=0.1",
                              facecolor=color, edgecolor="white", linewidth=2, alpha=0.85)
        ax.add_patch(rect)
        ax.text(x + box_w/2, 2.9, title, ha="center", va="center",
                fontsize=9, color="white", fontweight="bold")
        ax.text(x + box_w/2, 2.2, desc, ha="center", va="center",
                fontsize=7, color="white")

        if i < len(steps) - 1:
            arrow = FancyArrowPatch((x + box_w, 2.5), (x + box_w + gap, 2.5),
                                    arrowstyle="->", mutation_scale=20, color="#555", linewidth=2)
            ax.add_patch(arrow)

    # 失败回环箭头
    ax.annotate("", xy=(start_x + box_w/2, 1.3), xytext=(start_x + 4*(box_w+gap) + box_w/2, 1.3),
                arrowprops=dict(arrowstyle="->", color="#E74C3C", lw=2, connectionstyle="arc3,rad=0.3"))
    ax.text(7, 0.5, "失败 → 回到 Step ① (受 retry_budget 限制，默认 3 次)", ha="center", fontsize=9, color="#E74C3C")

    # 成本标注
    ax.text(7, 4.3, "成本: 仅 Step ③ 用 Sonnet ($0.0028/M cached)，其余走 Flash → 单次自愈 ≈ $0.003–$0.05",
            ha="center", fontsize=9, color="#333",
            bbox=dict(boxstyle="round", facecolor="#FFF9C4", alpha=0.8))

    plt.tight_layout()
    plt.savefig("/data/workspace/ai_test_platform/self_heal_flow.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✅ self_heal_flow.png")


if __name__ == "__main__":
    draw_architecture()
    draw_cost_comparison()
    draw_self_heal_flow()
    print("\n🎉 所有图表生成完成")
