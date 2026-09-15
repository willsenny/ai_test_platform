"""
WSGI 入口（见 settings.WSGI_APPLICATION = "config.wsgi.application"）
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
