"""
导入示例文档到 RAG 知识库

用法:
    python scripts/seed_demo.py
"""
import asyncio
import os
import sys

# 将 platform/ 加入 sys.path，使 `import apps.*` 可用
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "platform"))


async def seed_demo() -> int:
    """导入示例文档（PRD / 接口规范 / 历史缺陷），返回导入数量"""
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
    return len(docs)


if __name__ == "__main__":
    asyncio.run(seed_demo())
