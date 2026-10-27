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

# 生产部署批（#023，D-1）：ALLOWED_HOSTS 经 DJANGO_ALLOWED_HOSTS 环境变量
# 配置（逗号分隔），默认回落本地两地址；已去除原硬编码 '*' 通配——生产
# 域名必须显式经环境变量配置，避免误放行任意 Host 头。本地 runserver 与
# E2E 冒烟直连 127.0.0.1 均在默认回落内；Django 测试运行器自动追加
# 'testserver'，测试不受影响
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get(
        'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]

# 生产部署批（#023，D-1）：Django 4+ 对 admin 表单等跨源 POST 校验 Origin
# 头，公网域名下使用 admin 必须把站点完整来源（含 scheme）配进
# DJANGO_CSRF_TRUSTED_ORIGINS（逗号分隔，如 https://demo.example.com），
# 否则浏览器登录 admin 提交表单即 403；本地/同源访问默认空列表即可
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if o.strip()
]

# 生产部署批（#023，D-1）：反代 TLS 终止时后端感知不到 https，需让 Django
# 信任反代传入的 X-Forwarded-Proto 头。经 DJANGO_SECURE_PROXY_SSL_HEADER
# 配置，格式 'HTTP_X_FORWARDED_PROTO,https'（与 Django 文档一致），启用时
# 解析为元组；默认 None 不启用——仅当部署在可信反代之后时开启，直连暴露
# 时开启会被客户端伪造头欺骗（request.is_secure() 误判为 https）
_proxy_ssl_header = os.environ.get('DJANGO_SECURE_PROXY_SSL_HEADER', '')
if _proxy_ssl_header and ',' in _proxy_ssl_header:
    _header_name, _header_value = _proxy_ssl_header.split(',', 1)
    SECURE_PROXY_SSL_HEADER = (_header_name.strip(), _header_value.strip())
else:
    SECURE_PROXY_SSL_HEADER = None

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
    # 生产部署批（#023，D-4 用户裁决）：档位值 env 化（THROTTLE_LOGIN_MINUTE /
    # THROTTLE_LOGIN_DAILY），默认保持 10/min 与 50/day 现值不变；scope 键名
    # login_minute / login_daily 本身不改（apps/users/throttling.py 与
    # test_security_hardening.py 对键名有硬依赖）
    'DEFAULT_THROTTLE_RATES': {
        'login_minute': os.environ.get('THROTTLE_LOGIN_MINUTE', '10/min'),
        'login_daily': os.environ.get('THROTTLE_LOGIN_DAILY', '50/day'),
    },
    # 生产部署批（#023）：反代场景下 DRF 默认把整个 X-Forwarded-For 字符串当
    # 客户端身份，客户端伪造 XFF 前缀即可绕过按 IP 计数的登录限流；设
    # NUM_PROXIES=1 表示「前面恰有一跳可信代理」，取 XFF 末位（=最近一跳
    # 代理观测到的真实客户端 IP）作限流标识。请求无 XFF 头时回落
    # REMOTE_ADDR，Django test client 不带 XFF，#016 限流测试不受影响
    'NUM_PROXIES': 1,
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

# Email（生产部署批 #023，T-02 路线A：同步 SMTP，不动 Celery——用户裁决）
# 默认 console 后端（邮件打印到 stdout，本地开发零配置零外发）；生产 SMTP
# 经环境变量整组切换（见 .env.example 与 DEPLOY.md）。Django 测试运行器自动
# 切内存后端（mail.outbox），通知矩阵 16 项与新增邮件断言测试均不实际外发
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
# SMTP 端口默认 587（STARTTLS 常见搭配）；若供应商要求 465 隐式 TLS，需将
# EMAIL_USE_TLS 置 False 并按其文档确认端口（未引入 EMAIL_USE_SSL 键）
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
# 默认 True：切 SMTP 后端时漏配 TLS 会导致明文发信，宁可默认加密
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'webmaster@localhost')

# Redis 缓存（生产部署批 #023，D-2 机制预留）
# 设置 REDIS_URL 则 default 缓存指向 django-redis（依赖见 requirements.txt：
# redis / django-redis），供限流计数（#016 安全项1）等共享存储使用；未设置
# 则完全不写 CACHES，保持 Django 默认 locmem——单实例演示部署（gunicorn
# 单 worker / runserver）locmem 限流同样有效，本地与测试离线可跑；多 worker
# 部署各进程 locmem 独立计数会稀释限流效果，必须配置 REDIS_URL
REDIS_URL = os.environ.get('REDIS_URL', '')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.backend.RedisCache',
            'LOCATION': REDIS_URL,
        },
    }

# Celery（预留占位，当前未接线：定时任务以 process_scheduled 管理命令 +
# cron 替代，见 T-19 决策记录；T-02 邮件已走同步 SMTP 路线（#023 路线A），
# 亦不经 Celery——以下三行为历史占位，接线前勿依赖）
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_TIMEZONE = 'Asia/Shanghai'

# File upload
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 20MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
