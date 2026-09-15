from django.apps import AppConfig


class RagConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rag"
    verbose_name = "RAG 知识库"

    def ready(self):
        # Phase G：注册向量写入信号（TestCase / TestStepResult / SelfHealLog）
        from . import signals  # noqa: F401
