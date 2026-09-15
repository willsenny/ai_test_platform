from rest_framework import serializers

from .models import TestCase


class TestCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestCase
        fields = [
            "id",
            "project_id",
            "title",
            "preconditions",
            "steps",
            "assertions",
            "priority",
            "tags",
            "source",
            "target_url",
            "raw_steps",
            "last_run_status",
            "last_run_log",
            "last_run_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
