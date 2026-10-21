"""P0安全修复回归测试 - 账号安全四件套（对应评审意见 V1.1 致命#1/#2/#4）

覆盖：
- UserViewSet CRUD 权限收口（list/retrieve/update/destroy 仅编辑部，retrieve 另允许本人）
- 个人通道字段白名单（update_profile 不可改 roles/email）
- 编辑部管理通道（UserAdminSerializer 可调角色/重置密码）
- change_password 旧密码校验
"""
from django.contrib.auth import authenticate

from rest_framework.test import APIClient

from django.test import TestCase

from apps.users.models import User


def make_user(email, roles, password='pass12345', **extra):
    user = User.objects.create(email=email, name=extra.pop('name', email), roles=roles, **extra)
    user.set_password(password)
    user.save()
    return user


class UserCrudPermissionTests(TestCase):
    """致命#1：默认路由暴露的 list/update/destroy 必须仅编辑部可用"""

    def setUp(self):
        self.editor = make_user('editor@test.local', ['EDITOR'], name='编辑部')
        self.reviewer = make_user('reviewer@test.local', ['REVIEWER'], name='审稿人甲')
        self.author = make_user('author@test.local', ['AUTHOR'], name='作者甲')
        self.client = APIClient()

    def test_reviewer_cannot_list_users(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get('/api/users/')
        self.assertEqual(resp.status_code, 403)

    def test_editor_can_list_users(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get('/api/users/')
        self.assertEqual(resp.status_code, 200)

    def test_non_editor_cannot_patch_roles_to_editor(self):
        """致命#2：普通用户 PATCH 自己 roles=['EDITOR'] 必须被拒"""
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.patch(
            f'/api/users/{self.reviewer.user_id}/',
            {'roles': ['EDITOR']}, format='json',
        )
        self.assertEqual(resp.status_code, 403)
        self.reviewer.refresh_from_db()
        self.assertEqual(self.reviewer.roles, ['REVIEWER'])

    def test_non_editor_cannot_delete_user(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.delete(f'/api/users/{self.reviewer.user_id}/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(User.objects.filter(user_id=self.reviewer.user_id).exists())

    def test_non_editor_cannot_update_another_user(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.put(
            f'/api/users/{self.reviewer.user_id}/',
            {'name': '冒名'}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_retrieve_self_allowed_but_others_forbidden(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(f'/api/users/{self.author.user_id}/')
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(f'/api/users/{self.reviewer.user_id}/')
        self.assertEqual(resp.status_code, 403)

    def test_editor_can_patch_roles_via_admin_channel(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.patch(
            f'/api/users/{self.reviewer.user_id}/',
            {'roles': ['REVIEWER', 'AUTHOR']}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.reviewer.refresh_from_db()
        self.assertEqual(self.reviewer.roles, ['REVIEWER', 'AUTHOR'])

    def test_editor_reset_password_via_admin_channel(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.patch(
            f'/api/users/{self.reviewer.user_id}/',
            {'password': 'Reset12345'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('password', resp.data)
        self.assertIsNotNone(
            authenticate(username='reviewer@test.local', password='Reset12345')
        )


class UserProfileChannelTests(TestCase):
    """致命#2：update_profile 字段白名单——roles/email 不在个人可改范围"""

    def setUp(self):
        self.author = make_user('author@test.local', ['AUTHOR'], name='作者甲')
        self.client = APIClient()
        self.client.force_authenticate(user=self.author)

    def test_update_profile_changes_only_whitelisted_fields(self):
        resp = self.client.put('/api/users/update_profile/', {
            'name': '新笔名',
            'institution': '某大学',
            'research_areas': ['气候经济学'],
            # 以下为越权尝试，必须被忽略
            'roles': ['EDITOR'],
            'email': 'evil@test.local',
        }, format='json')
        self.assertEqual(resp.status_code, 200)

        self.author.refresh_from_db()
        self.assertEqual(self.author.name, '新笔名')
        self.assertEqual(self.author.institution, '某大学')
        self.assertEqual(self.author.roles, ['AUTHOR'])       # 未被篡改
        self.assertEqual(self.author.email, 'author@test.local')  # 未被篡改

    def test_update_profile_rejects_empty_name(self):
        resp = self.client.put('/api/users/update_profile/', {
            'name': '', 'institution': '', 'research_areas': [],
        }, format='json')
        self.assertEqual(resp.status_code, 400)


class ChangePasswordTests(TestCase):
    """致命#4：修改密码必须校验旧密码"""

    def setUp(self):
        self.author = make_user('author@test.local', ['AUTHOR'], name='作者甲')
        self.client = APIClient()
        self.client.force_authenticate(user=self.author)

    def test_change_password_with_wrong_old_password_rejected(self):
        resp = self.client.post('/api/users/change_password/', {
            'old_password': 'wrong-old',
            'new_password': 'NewPass12345',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

        # 密码未变
        self.assertIsNotNone(
            authenticate(username='author@test.local', password='pass12345')
        )

    def test_change_password_success(self):
        resp = self.client.post('/api/users/change_password/', {
            'old_password': 'pass12345',
            'new_password': 'NewPass12345',
        }, format='json')
        self.assertEqual(resp.status_code, 200)

        self.assertIsNone(authenticate(username='author@test.local', password='pass12345'))
        self.assertIsNotNone(authenticate(username='author@test.local', password='NewPass12345'))

    def test_change_password_min_length(self):
        resp = self.client.post('/api/users/change_password/', {
            'old_password': 'pass12345',
            'new_password': 'short',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
