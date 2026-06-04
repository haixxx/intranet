"""
Django settings for Intranet project.

Giai đoạn chuẩn hóa nền:
- Mặc định tắt DEBUG.
- Production bắt buộc có DJANGO_SECRET_KEY cố định.
- Module attendance_devices v1 mặc định tắt khỏi runtime.
- Celery beat mặc định tắt nếu chưa triển khai Celery/Redis.
- Vẫn hỗ trợ chạy HTTP trong mạng LAN nội bộ.
"""

from pathlib import Path
import os
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    """Đọc biến môi trường dạng boolean."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    """Đọc biến môi trường dạng danh sách phân tách bằng dấu phẩy."""
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


DJANGO_ENV = os.getenv("DJANGO_ENV", "dev").strip().lower()
IS_PRODUCTION = DJANGO_ENV in {"prod", "production"}

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError("Missing DJANGO_SECRET_KEY in production environment")
    SECRET_KEY = get_random_secret_key()

DEBUG = env_bool("DJANGO_DEBUG", default=False)

DEFAULT_ALLOWED_HOSTS = "192.168.1.100,localhost,127.0.0.1"
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS)

ENABLE_ATTENDANCE_DEVICES_V1 = env_bool("ENABLE_ATTENDANCE_DEVICES_V1", default=False)
ENABLE_CELERY_BEAT = env_bool("ENABLE_CELERY_BEAT", default=False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "apps.core",
    "apps.backoffice",
    "apps.audit",
    "apps.organization",
    "apps.hr",
    "apps.attendance",
    "apps.approvals",
    "apps.notifications",
    "apps.attendance_devices_v2",
]

# Module attendance_devices v1 đã ngừng dùng.
# Chỉ bật lại tạm thời khi cần kiểm tra dữ liệu/route legacy.
if ENABLE_ATTENDANCE_DEVICES_V1:
    INSTALLED_APPS.append("apps.attendance_devices")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "appserver.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "appserver.wsgi.application"
ASGI_APPLICATION = "appserver.asgi.application"

if env_bool("USE_POSTGRES", default=False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "intranet_db"),
            "USER": os.getenv("DB_USER", "intranet_user"),
            "PASSWORD": os.getenv("DB_PASSWORD", "change-me"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
            "OPTIONS": {},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

LANGUAGE_CODE = "vi"
LANGUAGES = [("vi", "Tiếng Việt"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]

TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / os.getenv("STATIC_ROOT", "staticfiles")

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / os.getenv("MEDIA_ROOT", "media")

# Django 5.x:
# STATICFILES_STORAGE đã deprecated. Dùng STORAGES để cấu hình storage mặc định
# và storage cho static files.
if DEBUG:
    STATICFILES_BACKEND = "django.contrib.staticfiles.storage.StaticFilesStorage"
else:
    STATICFILES_BACKEND = "whitenoise.storage.CompressedManifestStaticFilesStorage"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": STATICFILES_BACKEND,
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.User"
LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/backoffice/"
SESSION_COOKIE_AGE = 60 * 60 * 4
SESSION_COOKIE_HTTPONLY = True

# Giai đoạn hiện tại dùng HTTP nội bộ trong LAN.
SECURE_SSL_REDIRECT = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False
SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = True

DEFAULT_CSRF_TRUSTED = "http://192.168.1.100,http://localhost:8000,http://127.0.0.1:8000"
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", DEFAULT_CSRF_TRUSTED)

SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

ATTENDANCE_AGENT_RATE_LIMIT_REQUESTS_PER_HOUR = int(os.getenv("ATT_AGENT_RATE_LIMIT_PER_HOUR", "300"))
ATTENDANCE_RAW_EVENTS_MAX_BATCH_SIZE = int(os.getenv("ATT_RAW_EVENTS_MAX_BATCH_SIZE", "2000"))
ATTENDANCE_INGEST_HMAC_CLIENTS = {
    "win-client-01": os.getenv("ATT_HMAC_WIN_CLIENT_01", "replace-with-strong-secret-hex-or-base64")
}
ATTENDANCE_INGEST_HMAC_WINDOW_SECONDS = int(os.getenv("ATT_HMAC_WIN_SECONDS", "300"))

if ENABLE_CELERY_BEAT and ENABLE_ATTENDANCE_DEVICES_V1:
    CELERY_BEAT_SCHEDULE = {
        "resolve-raw-events-every-5-min": {
            "task": "attendance_devices.resolve_raw_events_employee",
            "schedule": 300,
            "args": [ATTENDANCE_RAW_EVENTS_MAX_BATCH_SIZE],
        }
    }
else:
    CELERY_BEAT_SCHEDULE = {}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        }
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "apps.attendance_devices_v2": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}
