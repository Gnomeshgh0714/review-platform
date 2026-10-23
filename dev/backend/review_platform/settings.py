"""
Django settings for review_platform project.
学术论文审稿协作平台 - 后端配置
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path=BASE_DIR / '.env'):
    """极简 .env 加载器：KEY=VALUE 逐行读取，已存在的环境变量不覆盖。

    避免引入 django-environ 等额外依赖；支持 # 注释与空行。
    """
    if not path.exists():
        return
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-k8$dbc2^z85lqoz1opjbxh4)bfowcq3ov+9^am0mf6j=@0hax_')

# V1.2 一般#13：DEBUG 兜底由 True 改为 False（安全默认，防 .env 缺失时
# 以调试模式对外服务）；本地开发经 .env / 环境变量显式设置
# DJANGO_DEBUG=True（见 backend/.env.example）。manage.py test 强制
# DEBUG=False，测试不受影响
DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'

# V1.2 建议#12：是否信任反向代理传入的 X-Forwarded-For。默认 False——
# 直连部署时 XFF 首段可被客户端任意伪造（知识库访问审计的 IP 字段会失真）；
# 仅当确认部署在 Nginx 等可信代理之后时经环境变量开启
TRUST_X_FORWARDED_FOR = os.environ.get('DJANGO_TRUST_X_FORWARDED_FOR', 'False') == 'True'

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    # #016 安全项3：refresh_token 轮换的黑名单存储（需执行 migrate 建表）
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    # Local apps
    'apps.users',
    'apps.notifications',
    'apps.files',
    'apps.tasks',
    'apps.forms',
    'apps.summaries',
    'apps.knowledge',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'review_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'review_platform.wsgi.application'

# Database - PostgreSQL 15（可用 backend/.env 覆盖，见 .env.example）
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DJANGO_DB_NAME', 'review_platform'),
        'USER': os.environ.get('DJANGO_DB_USER', 'review_user'),
        'PASSWORD': os.environ.get('DJANGO_DB_PASSWORD', 'review2026'),
        'HOST': os.environ.get('DJANGO_DB_HOST', 'localhost'),
        'PORT': os.environ.get('DJANGO_DB_PORT', '5432'),
    }
}

# Custom user model
AUTH_USER_MODEL = 'users.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (uploaded PDFs etc.)
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    # V1.2 一般#1：分页器支持 page_size 查询参数（上限 100），
    # 前端已传的 page_size（通知 50 / 仪表盘 5）自此生效；
    # 实现见 review_platform/pagination.py
    'DEFAULT_PAGINATION_CLASS': 'review_platform.pagination.StandardPagination',
    'PAGE_SIZE': 20,
    # #016 安全项1：登录限流档位（防暴力破解）——仅登录视图局部引用（见
    # apps/users/throttling.py），未设全局 DEFAULT_THROTTLE_CLASSES，其他接口不受影响。
    # 分钟档 10 次/分钟/IP 拦高频撞库（正常输错重试与 E2E 冒烟 5 次登录远低于此）；
    # 每日档 50 次/天/IP 兜底慢速尝试（较常见实践 100/day 从严，演示环境够用）
    'DEFAULT_THROTTLE_RATES': {
        'login_minute': '10/min',
        'login_daily': '50/day',
    },
}

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=12),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'USER_ID_FIELD': 'user_id',
    'USER_ID_CLAIM': 'user_id',
    # #016 安全项3：refresh_token 轮换——刷新时签发新 refresh 并将旧 token 拉黑，
    # 泄露的旧 refresh 无法二次使用；刷新端点见 apps/users/urls.py 的
    # users/token/refresh/（TokenRefreshView），黑名单表来自 token_blacklist 迁移
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# CORS（#016 安全项2：白名单收紧，替换原 CORS_ALLOW_ALL_ORIGINS = True 的全放开）
# 本地开发内置 Vite dev server 两个来源；生产经环境变量 CORS_ALLOWED_ORIGINS
# 扩展（逗号分隔，见 backend/.env.example）。E2E/测试直连 127.0.0.1 不走 CORS 预检，不受影响
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
] + [o.strip() for o in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]

# Celery
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_TIMEZONE = 'Asia/Shanghai'

# File upload
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 20MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
