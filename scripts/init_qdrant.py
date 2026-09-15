"""
初始化脚本

1. 启动基础设施 (docker-compose up -d)
2. 初始化 Qdrant collection
3. 导入示例文档到 RAG
4. 验证模型路由
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def init_qdrant():
    """初始化 Qdrant collection"""
    from apps.rag.service import ensure_collection
    await ensure_collection(vector_size=1024)
    print("✅ Qdrant collection 'test_knowledge' ready")


async def seed_demo():
    """导入示例文档"""
    from apps.rag.service import ingest_document, Document

    docs = [
        Document(
            content="""
            用户登录功能需求：
            1. 支持手机号 + 短信验证码登录
            2. 验证码 6 位数字，5 分钟内有效
            3. 同一手机号 1 分钟内只能发送一次验证码
            4. 连续 5 次错误验证码后，账号锁定 30 分钟
            5. 登录成功跳转首页，Session 有效期 7 天
            """,
            source="prd/user_login.md",
            doc_type="prd",
            project_id="demo",
        ),
        Document(
            content="""
            POST /api/v1/auth/send-code
            Request: {"phone": "13800138000"}
            Response: {"code": 0, "message": "发送成功"}
            限流: 同一 IP 每分钟最多 10 次

            POST /api/v1/auth/login
            Request: {"phone": "...", "code": "123456"}
            Response: {"token": "jwt_token", "expires_in": 604800}
            错误码: 4001 验证码错误, 4002 验证码过期, 4003 账号锁定
            """,
            source="api/auth.yaml",
            doc_type="api_spec",
            project_id="demo",
        ),
        Document(
            content="""
            历史缺陷 #1234: 验证码在 4分59秒时过期判定失败
            原因: 服务端使用整数除法，边界值处理错误
            修复: 使用精确时间戳比较

            历史缺陷 #1567: 频繁请求限流未生效
            原因: Redis key 过期时间设置错误
            修复: 统一使用 TTL 机制
            """,
            source="bugs/auth.txt",
            doc_type="bug",
            project_id="demo",
        ),
    ]

    for doc in docs:
        await ingest_document(doc)
        print(f"  ✅ {doc.source}")

    print(f"\n🎉 已导入 {len(docs)} 份示例文档")


async def verify_model_routing():
    """验证模型路由配置"""
    from apps.agent.router import route, ModelTier, PRICING

    print("\n=== 模型路由验证 ===")
    tests = [
        ("generate_testcase", ModelTier.L1_FLASH),
        ("generate_steps", ModelTier.L1_FLASH),
        ("refactor_code", ModelTier.L2_PRO),
        ("self_heal_repair", ModelTier.L3_SONNET),
    ]
    for task, expected_tier in tests:
        cfg = route(task)
        status = "✅" if cfg.tier == expected_tier else "❌"
        print(f"  {status} {task:<25} → {cfg.tier.value:<12} ({cfg.model})")


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
