"""用户模块测试 - 登录 / 创建账号权限（编辑部专属）与密码初始化"""
from django.contrib.auth import authenticate

from rest_framework.test import APIClient

from django.test import TestCase

from apps.users.models import User


def make_user(email, roles, password='pass12345', **extra):
    user = User.objects.create(email=email, name=extra.pop('name', email), roles=roles, **extra)
    user.set_password(password)
    user.save()
    return user


class LoginTests(TestCase):

    def test_login_success_returns_jwt(self):
        make_user('editor@test.local', ['EDITOR'])
        client = APIClient()
        resp = client.post('/api/users/login/',
                           {'email': 'editor@test.local', 'password': 'pass12345'},
                           format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)
        self.assertEqual(resp.data['user']['email'], 'editor@test.local')

    def test_login_wrong_password(self):
        make_user('editor@test.local', ['EDITOR'])
        client = APIClient()
        resp = client.post('/api/users/login/',
                           {'email': 'editor@test.local', 'password': 'wrong'},
                           format='json')
        self.assertEqual(resp.status_code, 401)

    def test_login_unknown_user(self):
        client = APIClient()
        resp = client.post('/api/users/login/',
                           {'email': 'nobody@test.local', 'password': 'whatever'},
                           format='json')
        self.assertEqual(resp.status_code, 401)

    def test_authenticate_with_email(self):
        make_user('r@test.local', ['REVIEWER'])
        self.assertIsNotNone(authenticate(username='r@test.local', password='pass12345'))
        self.assertIsNone(authenticate(username='r@test.local', password='bad'))


class CreateUserTests(TestCase):
    """创建账号：仅编辑部可建（PRD §3.1.1），密码必须初始化为可登录状态"""

    def setUp(self):
        self.editor = make_user('editor@test.local', ['EDITOR'])
        self.reviewer = make_user('reviewer@test.local', ['REVIEWER'])
        self.client = APIClient()

    def test_editor_can_create_user_with_explicit_password(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post('/api/users/', {
            'name': '新审稿人', 'email': 'new@test.local',
            'roles': ['REVIEWER'], 'research_areas': ['气候经济学'],
            'password': 'Init12345',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertNotIn('password', resp.data)  # write_only 不回显

        # 新账号可用指定密码登录
        self.assertIsNotNone(
            authenticate(username='new@test.local', password='Init12345')
        )

    def test_created_user_defaults_to_loginable_password(self):
        """未传密码时使用默认密码 changeme123（修复：此前账号无密码、无法登录）"""
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post('/api/users/', {
            'name': '新作者', 'email': 'author2@test.local', 'roles': ['AUTHOR'],
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertIsNotNone(
            authenticate(username='author2@test.local', password='changeme123')
        )

    def test_reviewer_cannot_create_user(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/users/', {
            'name': '越权账号', 'email': 'hack@test.local', 'roles': ['EDITOR'],
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(email='hack@test.local').exists())

    def test_anonymous_cannot_create_user(self):
        """修复回归：此前 create 为 AllowAny，未登录也可自建 EDITOR 账号"""
        resp = self.client.post('/api/users/', {
            'name': '匿名账号', 'email': 'anon@test.local', 'roles': ['EDITOR'],
        }, format='json')
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(User.objects.filter(email='anon@test.local').exists())


class UserMiscTests(TestCase):

    def test_user_id_generation_format(self):
        user = make_user('u1@test.local', ['REVIEWER'])
        # 格式：U-YYYYMMDD-NNNN
        from django.utils import timezone
        prefix = f'U-{timezone.now().strftime("%Y%m%d")}'
        self.assertTrue(user.user_id.startswith(prefix))
        self.assertEqual(len(user.user_id.split('-')), 3)

        user2 = make_user('u2@test.local', ['REVIEWER'])
        self.assertNotEqual(user.user_id, user2.user_id)

    def test_role_properties(self):
        u = make_user('m@test.local', ['EDITOR', 'REVIEWER'])
        self.assertTrue(u.is_editor)
        self.assertTrue(u.is_reviewer)
        self.assertFalse(u.is_author)
