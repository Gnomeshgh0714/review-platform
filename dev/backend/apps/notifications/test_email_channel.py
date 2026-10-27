"""T-02 邮件通道测试（生产部署批 #023，路线A：同步 SMTP）

覆盖三个核心场景与用户创建第二触点（PRD §6.2.1）：
- invitation 通知站内信 + 邮件双通道（服务级触发，断言 Notification 与
  mail.outbox 双落地）
- 收件人 email 为空：只落站内信，邮件跳过
- 邮件发送异常：站内信照常创建，异常被吞（logger.warning，不抛出）
- 编辑部创建用户：账号创建成功并发邀请邮件，显式密码随邮件告知本人
- 编辑部创建用户未传密码：邀请邮件按缺省口径含 changeme123

Django 测试运行器自动把邮件切到内存后端（mail.outbox），不实际外发。
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase

from rest_framework.test import APIClient

from apps.notifications.models import Notification
from apps.notifications.services import NotificationService
from apps.tasks.models import ReviewTask, Template, ReviewAssignment
from apps.users.models import User


def make_user(email, roles, name, **extra):
    return User.objects.create(email=email, name=name, roles=roles, **extra)


def make_template():
    """两维模板：与 test_p2_matrix 相同的最小合法形态"""
    return Template.objects.create(
        template_name='邮件通道测试模板', template_type='SYSTEM_DEFAULT',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义'},
            {'dimensionId': 'D2', 'dimensionName': '创新性'},
        ],
    )


def make_task(author):
    template = make_template()
    return ReviewTask.objects.create(
        title='邮件通道测试稿件', abstract='摘要', keywords=['a'],
        subject_area='经济学', manuscript_type='论文',
        manuscript_file='email-test.pdf', review_mode='SINGLE_BLIND',
        deadline=date.today() + timedelta(days=14),
        template_id=template.template_id, author_user_id=author,
        status='REVIEWING',
    )


def make_assignment(task, reviewer, status='INVITED'):
    return ReviewAssignment.objects.create(
        task=task, reviewer=reviewer,
        deadline=date.today() + timedelta(days=14),
        invitation_expiry=date.today() + timedelta(days=3),
        assignment_status=status,
    )


class InvitationEmailChannelTests(TestCase):
    """invitation 通知的站内信 + 邮件双通道与容错"""

    def setUp(self):
        self.author = make_user('em-author@test.local', ['AUTHOR'], '作者')
        self.reviewer = make_user('em-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.task = make_task(self.author)
        self.assignment = make_assignment(self.task, self.reviewer)

    def test_invitation_notifies_both_channels(self):
        """send_invitation 后站内信与邮件双落地，收件人/主题/正文正确"""
        NotificationService.send_invitation(self.task, self.reviewer, self.assignment)

        self.assertEqual(
            Notification.objects.filter(
                user=self.reviewer, type='INVITATION').count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.reviewer.email])
        self.assertIn('审稿邀请', message.subject)
        self.assertIn(self.task.task_id, message.body)
        self.assertIn(self.task.title, message.body)

    def test_empty_email_skips_mail_only(self):
        """收件人 email 为空：邮件跳过，站内信照常创建"""
        no_email = User.objects.create(
            email='', name='无邮箱审稿人', roles=['REVIEWER'])
        NotificationService.send_invitation(self.task, no_email, self.assignment)

        self.assertEqual(
            Notification.objects.filter(
                user=no_email, type='INVITATION').count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    @patch('apps.notifications.email.send_mail', side_effect=Exception('SMTP 故障'))
    def test_send_failure_does_not_block_notification(self, _mock):
        """邮件发送异常：只记日志不抛出，站内信照常创建（容错口径）"""
        NotificationService.send_invitation(self.task, self.reviewer, self.assignment)

        self.assertEqual(
            Notification.objects.filter(
                user=self.reviewer, type='INVITATION').count(), 1)


class AccountInvitationEmailTests(TestCase):
    """编辑部创建用户的邀请邮件（PRD §6.2.1 第二触点，#023 路线A）"""

    def setUp(self):
        self.editor = make_user('em-editor@test.local', ['EDITOR'], '编辑')
        self.client = APIClient()

    def test_create_user_sends_invitation_email_with_explicit_password(self):
        """创建成功即发邀请邮件，显式密码随邮件告知本人"""
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post('/api/users/', {
            'name': '新审稿人',
            'email': 'new-reviewer@test.local',
            'roles': ['REVIEWER'],
            'password': 'InitPass123!',
        }, format='json')
        self.assertEqual(resp.status_code, 201)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['new-reviewer@test.local'])
        self.assertIn('账号已创建', message.subject)
        self.assertIn('新审稿人', message.body)
        self.assertIn('InitPass123!', message.body)

    def test_create_user_without_password_uses_default_in_mail(self):
        """未传密码：邀请邮件按缺省口径含 changeme123（首次登录后修改）"""
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post('/api/users/', {
            'name': '默认密码作者',
            'email': 'default-pass@test.local',
            'roles': ['AUTHOR'],
        }, format='json')
        self.assertEqual(resp.status_code, 201)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('changeme123', mail.outbox[0].body)
