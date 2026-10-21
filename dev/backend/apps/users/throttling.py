"""#016 安全项1：登录接口限流（防暴力破解）

双层档位（数值在 settings.py REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] 调整）：
- 分钟档 10 次/分钟/IP：拦高频撞库；正常使用（输错重试、E2E 冒烟 5 次登录）远低于限值
- 每日档 50 次/天/IP：兜底慢速分布式尝试（较常见实践 100/day 从严，演示环境够用）

设计说明：
- 仅登录视图局部引用（UserViewSet.get_throttles），REST_FRAMEWORK 未设全局
  DEFAULT_THROTTLE_CLASSES，其他接口不受影响；超限由 DRF 返回 429
- 计数走 Django 默认 cache（当前为进程内 locmem）；生产多 worker 部署时各进程
  独立计数会稀释限流效果，上线前建议为 CACHES 配置 Redis
"""
from rest_framework.throttling import SimpleRateThrottle


class _LoginThrottle(SimpleRateThrottle):
    """登录限流基类：按客户端 IP 计数（登录请求发生在认证之前，无用户可依赖）"""

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class LoginMinuteThrottle(_LoginThrottle):
    """#016 安全项1：登录分钟档限流——10 次/分钟/IP，拦高频撞库"""
    scope = 'login_minute'


class LoginDailyThrottle(_LoginThrottle):
    """#016 安全项1：登录每日档限流——50 次/天/IP，兕底慢速尝试"""
    scope = 'login_daily'
