"""#016 安全加固批回归测试

覆盖决策 #013 起挂账、本批（#016）落地的安全项：
- 安全项1：登录接口限流——限值内正常返回，超限返回 429（防暴力破解）
- 安全项3：refresh_token 轮换——刷新返回新 access + 新 refresh，
  旧 refresh 被拉黑不可二次使用，新 refresh 可继续轮换
"""
from django.core.cache import cache
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from apps.users.models import User


def make_user(email, roles, password='pass12345', **extra):
    user = User.objects.create(email=email, name=extra.pop('name', email), roles=roles, **extra)
    user.set_password(password)
    user.save()
    return user


class LoginThrottleTests(TestCase):
    """安全项1：登录限流——限值内可用，超限 429"""

    def setUp(self):
        make_user('editor@test.local', ['EDITOR'])
        self.client = APIClient()
        # 限流计数走进程内 cache，每个用例前清零，避免用例间互相污染计数
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_login_within_limit_returns_200(self):
        """默认档位（10 次/分钟/IP）下单次登录不受限流影响"""
        resp = self.client.post('/api/users/login/',
                                {'email': 'editor@test.local', 'password': 'pass12345'},
                                format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

    def test_login_exceeds_minute_limit_returns_429(self):
        """分钟档超限：第 3 次（档位临时降为 2/min）返回 429，即使密码正确也被拒"""
        # DRF throttle 档位在类导入时解析，override_settings 不生效，直接改共享表
        old_rate = SimpleRateThrottle.THROTTLE_RATES['login_minute']
        SimpleRateThrottle.THROTTLE_RATES['login_minute'] = '2/min'
        try:
            # 前两次：限内，凭据错误返回 401（模拟撞库尝试）
            for _ in range(2):
                resp = self.client.post('/api/users/login/',
                                        {'email': 'editor@test.local', 'password': 'wrong'},
                                        format='json')
                self.assertEqual(resp.status_code, 401)
            # 第 3 次：超限返回 429——且密码正确也被拦（限流先于凭据校验）
            resp = self.client.post('/api/users/login/',
                                    {'email': 'editor@test.local', 'password': 'pass12345'},
                                    format='json')
            self.assertEqual(resp.status_code, 429)
        finally:
            SimpleRateThrottle.THROTTLE_RATES['login_minute'] = old_rate


class RefreshTokenRotationTests(TestCase):
    """安全项3：refresh_token 轮换（ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION）"""

    def setUp(self):
        make_user('author@test.local', ['AUTHOR'])
        self.client = APIClient()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _login_refresh(self):
        resp = self.client.post('/api/users/login/',
                                {'email': 'author@test.local', 'password': 'pass12345'},
                                format='json')
        self.assertEqual(resp.status_code, 200)
        return resp.data['refresh']

    def _refresh(self, token):
        return self.client.post('/api/users/token/refresh/',
                                {'refresh': token}, format='json')

    def test_rotation_returns_new_access_and_refresh(self):
        """刷新响应同时携带新 access 与新 refresh（轮换开启的标志）"""
        old_refresh = self._login_refresh()

        resp = self._refresh(old_refresh)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)  # 无轮换时该字段不存在
        self.assertNotEqual(resp.data['refresh'], old_refresh)

    def test_blacklisted_old_refresh_rejected(self):
        """旧 refresh 刷新后即被拉黑：再次使用返回 401（泄露 token 无法二次使用）"""
        old_refresh = self._login_refresh()
        resp = self._refresh(old_refresh)
        self.assertEqual(resp.status_code, 200)

        resp = self._refresh(old_refresh)
        self.assertEqual(resp.status_code, 401)

    def test_new_refresh_keeps_rotation_chain(self):
        """新 refresh 可继续刷新——轮换链路对正常用户持续可用"""
        refresh = self._login_refresh()
        for _ in range(2):
            resp = self._refresh(refresh)
            self.assertEqual(resp.status_code, 200)
            refresh = resp.data['refresh']
