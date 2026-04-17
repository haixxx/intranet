"""
settings.py (tạm thời toàn bộ HTTP cho UI và API)
- Không ép HTTPS.
- Cookie phiên/CSRF KHÔNG 'secure' để hoạt động trên HTTP.
- CSRF_TRUSTED_ORIGINS chỉ dùng http cho 192.168.1.100.
"""

from pathlib import Path
import os
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", get_random_secret_key())
# Tạm thời để True cho dev; khi ổn định có thể chuyển False
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"

DEFAULT_ALLOWED = "192.168.1.100,localhost,127.0.0.1"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", DEFAULT_ALLOWED).split(",") if h.strip()]

INSTALLED_APPS = [
    'django.contrib.admin','django.contrib.auth','django.contrib.contenttypes',
    'django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles',
    'apps.core','apps.backoffice','apps.audit','apps.organization',
    'apps.hr','apps.attendance','apps.approvals','apps.notifications',
    'apps.attendance_devices',
    'apps.attendance_devices_v2',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'appserver.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

WSGI_APPLICATION = 'appserver.wsgi.application'
ASGI_APPLICATION = 'appserver.asgi.application'

if os.getenv("USE_POSTGRES", "False") == "True":
   DATABASES = {'default': {
      'ENGINE': 'django.db.backends.postgresql',
       'NAME': os.getenv("DB_NAME", "django_db"),
       'USER': os.getenv("DB_USER", "django_user"),
       'PASSWORD': os.getenv("DB_PASSWORD", "StrongPasswordHere"),
       'HOST': os.getenv("DB_HOST", "localhost"),
       'PORT': os.getenv("DB_PORT", "5432"),
       'CONN_MAX_AGE': int(os.getenv("DB_CONN_MAX_AGE", "60")),
       'OPTIONS': {},
   }}
else:
   DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'django_db',
#         'USER': 'django_user',
#         'PASSWORD': 'StrongPasswordHere',
#         'HOST': 'localhost',
#         'PORT': '5432',
#         'CONN_MAX_AGE': 60,
#     }
# }

LANGUAGE_CODE = 'vi'
LANGUAGES = [('vi','Tiếng Việt'),('en','English')]
LOCALE_PATHS = [BASE_DIR / 'locale']

TIME_ZONE = 'Asia/Ho_Chi_Minh'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

if DEBUG:
    STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
else:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'core.User'
LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/backoffice/'
SESSION_COOKIE_AGE = 60 * 60 * 4
SESSION_COOKIE_HTTPONLY = True

# Toàn bộ HTTP
SECURE_SSL_REDIRECT = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False
# Không cần SECURE_PROXY_SSL_HEADER khi không dùng HTTPS
SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = True

# Chỉ http (nếu sau này dùng hostname nội bộ, thêm vào đây)
DEFAULT_CSRF_TRUSTED = "http://192.168.1.100"
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", DEFAULT_CSRF_TRUSTED).split(",") if o.strip()]

SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

ATTENDANCE_AGENT_RATE_LIMIT_REQUESTS_PER_HOUR = int(os.getenv("ATT_AGENT_RATE_LIMIT_PER_HOUR","300"))
ATTENDANCE_RAW_EVENTS_MAX_BATCH_SIZE = int(os.getenv("ATT_RAW_EVENTS_MAX_BATCH_SIZE","2000"))
ATTENDANCE_INGEST_HMAC_CLIENTS = {"win-client-01": os.getenv("ATT_HMAC_WIN_CLIENT_01","replace-with-strong-secret-hex-or-base64")}
ATTENDANCE_INGEST_HMAC_WINDOW_SECONDS = int(os.getenv("ATT_HMAC_WIN_SECONDS","300"))

CELERY_BEAT_SCHEDULE = {
    "resolve-raw-events-every-5-min": {"task":"attendance_devices.resolve_raw_events_employee","schedule":300,"args":[ATTENDANCE_RAW_EVENTS_MAX_BATCH_SIZE]}
}

LOGGING = {
    "version":1,"disable_existing_loggers":False,
    "handlers":{"console":{"class":"logging.StreamHandler"}},
    "loggers":{"django.request":{"handlers":["console"],"level":"INFO"},
               "apps.attendance_devices":{"handlers":["console"],"level":"INFO"}},
}