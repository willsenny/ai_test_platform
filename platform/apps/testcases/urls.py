"""
TestCase URLs（挂载于 /api/v1/testcases/）
"""
from rest_framework.routers import DefaultRouter

from .views import TestCaseViewSet

router = DefaultRouter()
router.register("", TestCaseViewSet, basename="testcase")

urlpatterns = router.urls
