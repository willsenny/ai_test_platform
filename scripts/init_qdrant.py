"""
初始化脚本

1. 启动基础设施 (docker-compose up -d)
2. 初始化 Qdrant collection
3. 导入示例文档到 RAG（见 seed_demo.py）
4. 验证模型路由 (Flash-Only)
"""
import asyncio
import sys
import os

# 将 platform/ 加入 sys.path，使 `import apps.*` 可用（脚本可从任意目录运行）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "platform"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))


async def init_qdrant():
    """初始化 Qdrant collection"""
    from apps.rag.service import ensure_collection
    await ensure_collection(vector_size=1024)
    print("✅ Qdrant collection 'test_knowledge' ready")


async def seed_demo():
    """导入示例文档（委托给 scripts/seed_demo.py）"""
    from seed_demo import seed_demo as _seed
    return await _seed()


async def verify_model_routing():
    """验证模型路由配置（Flash-Only + reasoning 档位）"""
    from apps.agent.router import route, ReasoningLevel

    print("\n=== 模型路由验证 (Flash-Only) ===")
    tests = [
        ("generate_testcase", ReasoningLevel.LOW),
        ("generate_steps", ReasoningLevel.LOW),
        ("refactor_code", ReasoningLevel.HIGH),
        ("self_heal_repair", ReasoningLevel.HIGH),
    ]
    for task, expected in tests:
        cfg = route(task)
        actual = cfg.reasoning_effort
        ok = (
            actual is None
            if expected == ReasoningLevel.LOW
            else actual == expected.value
        )
        status = "✅" if ok else "❌"
        print(f"  {status} {task:<25} → {(actual or 'low'):<6} ({cfg.model})")


async def main():
    print("🚀 初始化 AI 测试管理平台...\n")

    print("1. 初始化 Qdrant...")
    await init_qdrant()

    print("\n2. 导入示例文档...")
    await seed_demo()

    print("\n3. 验证模型路由...")
    await verify_model_routing()

    print("\n" + "=" * 50)
    print("✅ 初始化完成！")
    print("=" * 50)
    print("\n下一步:")
    print("  cd platform && python manage.py runserver")
    print("  # 或在 OpenCode 中开发")
    print("  cd opencode && opencode .")


if __name__ == "__main__":
    asyncio.run(main())
