"""#017 测试补课 —— 通知矩阵断言测试（决策 #014 提请的测试补课挂账项）

按「动作 → 谁收到什么类型通知 / 谁不收到」的矩阵为核心格子写断言，
主链全部走 API 级端到端（触发点在各业务 view 内），辅以服务级补充格
子与通知 API 的用户隔离断言：

主链（API 级）：
- 创建任务   → 作者 TASK_CREATED（编辑部/无关作者不收）
- 分配审稿人 → 被分配审稿人 INVITATION（未分配审稿人/作者/编辑部不收）
- 接受邀请   → 所有 EDITOR 用户 ACCEPT（含操作无关的另一位编辑；
               审稿人本人/作者不收）
- 拒绝邀请   → 所有 EDITOR 用户 REJECT（作者/审稿人不收）
- 提交意见   → 所有 EDITOR 用户 SUBMIT（审稿人/作者不收）
- 汇总报告   → 所有 EDITOR 用户 SUMMARIZE（作者/审稿人不收）
- 终审决策   → 作者 DECIDE（编辑部/审稿人不收）

既有行为锁定（定版裁决 O-1 已变更，2026-10-23）：
- make_decision publish=False 时仍向作者发送 DECIDE 通知，只告知
  终审决策结果，不含审稿意见详情（send_decide 内部按
  publish_opinions_to_author 区分意见公开状态文案）。
- 编辑部广播（ACCEPT/REJECT/SUBMIT/SUMMARIZE）含执行操作的编辑本人。

服务级补充格子：
- REMIND 仅通知目标审稿人（作者/编辑部不收）
- OVERDUE 通知审稿人 + 全体编辑部（作者不收）
- 停用（is_active=False）编辑不进入编辑部广播

通知 API 用户隔离：
- GET /api/notifications/ 仅返回本人通知；unread_count 按人隔离；
  retrieve 他人通知 404；mark_read 无法标记他人通知。
"""
from datetime import date, timedelta

from rest_framework.test import APIClient

from django.test import TestCase

from apps.notifications.models import Notification
from apps.notifications.services import NotificationService
from apps.tasks.models import ReviewTask, Template, ReviewAssignment
from apps.users.models import User


def make_user(email, roles, name, is_active=True):
    return User.objects.create(
        email=email, name=name, roles=roles, is_active=is_active)


def make_template():
    """两维模板：FormService.validate_opinion 要求表单维度数量在 2-8"""
    return Template.objects.create(
        template_name='通知矩阵测试模板', template_type='SYSTEM_DEFAULT',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义'},
            {'dimensionId': 'D2', 'dimensionName': '创新性'},
        ],
    )


def make_task(author, status='REVIEWING', **kwargs):
    template = make_template()
    defaults = dict(
        title='通知矩阵测试稿件', abstract='摘要', keywords=['a', 'b', 'c'],
        subject_area='经济学', manuscript_type='论文',
        manuscript_file='matrix-test.pdf', review_mode='SINGLE_BLIND',
        deadline=date.today() + timedelta(days=14),
        template_id=template.template_id, author_user_id=author, status=status,
    )
    defaults.update(kwargs)
    return ReviewTask.objects.create(**defaults)


def make_assignment(task, reviewer, status='ACCEPTED'):
    return ReviewAssignment.objects.create(
        task=task, reviewer=reviewer,
        deadline=date.today() + timedelta(days=14),
        invitation_expiry=date.today() + timedelta(days=3),
        assignment_status=status,
    )


def valid_submit_payload(task):
    """满足 FormService.validate_opinion 全部校验的最小合法提交"""
    return {
        'task_id': task.task_id,
        'dimension_scores': [
            {'dimensionId': 'D1', 'score': 4, 'comment': '研' * 50},
            {'dimensionId': 'D2', 'score': 5, 'comment': '创' * 50},
        ],
        'recommendation': 'MINOR_REVISION',
        'overall_comment': '评' * 100,
    }


# ==================== 主链 API 推进 helpers ====================

def api_create_task(client, editor, template, author):
    client.force_authenticate(user=editor)
    resp = client.post('/api/tasks/', {
        'title': '通知矩阵测试稿件',
        'abstract': '测试摘要',
        'keywords': ['计量', '面板', '因果'],
        'subject_area': '经济学',
        'manuscript_type': '论文',
        'manuscript_file': 'matrix-test.pdf',
        'review_mode': 'SINGLE_BLIND',
        'expected_reviewer_count': 1,
        'deadline': (date.today() + timedelta(days=30)).isoformat(),
        'template_id': template.template_id,
        'author_user_id': author.user_id,
    }, format='json')
    assert resp.status_code == 201, resp.data
    return ReviewTask.objects.get(task_id=resp.data['task_id'])


def api_assign(client, editor, task, *reviewers):
    client.force_authenticate(user=editor)
    return client.post(
        f'/api/tasks/{task.task_id}/assign_reviewers/',
        {'reviewer_user_ids': [r.user_id for r in reviewers]},
        format='json')


def api_accept(client, reviewer, task):
    client.force_authenticate(user=reviewer)
    return client.post(
        f'/api/tasks/{task.task_id}/accept_invitation/', format='json')


def api_reject(client, reviewer, task, reason='时间冲突无法承担'):
    client.force_authenticate(user=reviewer)
    return client.post(
        f'/api/tasks/{task.task_id}/reject_invitation/',
        {'reason': reason}, format='json')


def api_submit(client, reviewer, task):
    client.force_authenticate(user=reviewer)
    return client.post(
        '/api/opinions/submit/', valid_submit_payload(task), format='json')


def api_summarize(client, editor, task):
    client.force_authenticate(user=editor)
    return client.post(
        '/api/summaries/generate/', {'task_id': task.task_id},
        format='json')


def api_decide(client, editor, task, publish=True):
    client.force_authenticate(user=editor)
    return client.post(
        f'/api/tasks/{task.task_id}/make_decision/',
        {'decision': 'ACCEPT', 'notes': '决' * 120, 'publish': publish},
        format='json')


def drive_to_reviewing(client, editor, reviewer, author, template):
    task = api_create_task(client, editor, template, author)
    resp = api_assign(client, editor, task, reviewer)
    assert resp.status_code == 200, resp.data
    resp = api_accept(client, reviewer, task)
    assert resp.status_code == 200, resp.data
    return task


def drive_to_submitted(client, editor, reviewer, author, template):
    task = drive_to_reviewing(client, editor, reviewer, author, template)
    resp = api_submit(client, reviewer, task)
    assert resp.status_code == 201, resp.data
    return task


def drive_to_summarized(client, editor, reviewer, author, template):
    task = drive_to_submitted(client, editor, reviewer, author, template)
    resp = api_summarize(client, editor, task)
    assert resp.status_code == 201, resp.data
    return task


def notification_types(user, ntype=None):
    qs = Notification.objects.filter(user=user)
    if ntype:
        qs = qs.filter(type=ntype)
    return qs


class NotificationMatrixMainChainTests(TestCase):
    """主链矩阵：分配→审稿人、接受/提交/汇总→编辑部、终审→作者（API 级）"""

    def setUp(self):
        self.editor_a = make_user(
            'mx-editor-a@test.local', ['EDITOR'], '编辑甲')
        self.editor_b = make_user(
            'mx-editor-b@test.local', ['EDITOR'], '编辑乙')
        self.author = make_user(
            'mx-author@test.local', ['AUTHOR'], '作者')
        self.other_author = make_user(
            'mx-author-2@test.local', ['AUTHOR'], '无关作者')
        self.reviewer_a = make_user(
            'mx-ra@test.local', ['REVIEWER'], '审稿人甲')
        self.reviewer_b = make_user(
            'mx-rb@test.local', ['REVIEWER'], '审稿人乙')
        self.template = make_template()
        self.client = APIClient()

    def test_create_task_notifies_author_only(self):
        task = api_create_task(self.client, self.editor_a, self.template,
                               self.author)
        self.assertEqual(
            notification_types(self.author, 'TASK_CREATED').count(), 1)
        # 创建任务的编辑本人、无关作者、审稿人均不收
        self.assertEqual(
            notification_types(self.editor_a, 'TASK_CREATED').count(), 0)
        self.assertEqual(
            notification_types(self.other_author).count(), 0)
        self.assertEqual(
            notification_types(self.reviewer_a).count(), 0)

    def test_assign_notifies_only_invited_reviewers(self):
        task = api_create_task(self.client, self.editor_a, self.template,
                               self.author)
        resp = api_assign(self.client, self.editor_a, task, self.reviewer_a)
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(
            notification_types(self.reviewer_a, 'INVITATION').count(), 1)
        # 未被分配的审稿人、作者、编辑部分配人不收 INVITATION
        self.assertEqual(
            notification_types(self.reviewer_b, 'INVITATION').count(), 0)
        self.assertEqual(
            notification_types(self.author, 'INVITATION').count(), 0)
        self.assertEqual(
            notification_types(self.editor_a, 'INVITATION').count(), 0)

    def test_accept_notifies_all_editors(self):
        task = drive_to_reviewing(
            self.client, self.editor_a, self.reviewer_a, self.author,
            self.template)
        # drive_to_reviewing 内含一次 accept：两位编辑（含未操作者乙）各 1 条
        self.assertEqual(
            notification_types(self.editor_a, 'ACCEPT').count(), 1)
        self.assertEqual(
            notification_types(self.editor_b, 'ACCEPT').count(), 1)
        # 审稿人本人、作者、其他审稿人不收
        self.assertEqual(
            notification_types(self.reviewer_a, 'ACCEPT').count(), 0)
        self.assertEqual(
            notification_types(self.reviewer_b, 'ACCEPT').count(), 0)
        self.assertEqual(
            notification_types(self.author, 'ACCEPT').count(), 0)

    def test_reject_notifies_all_editors(self):
        task = api_create_task(self.client, self.editor_a, self.template,
                               self.author)
        api_assign(self.client, self.editor_a, task, self.reviewer_a)
        resp = api_reject(self.client, self.reviewer_a, task)
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(
            notification_types(self.editor_a, 'REJECT').count(), 1)
        self.assertEqual(
            notification_types(self.editor_b, 'REJECT').count(), 1)
        # 审稿人本人、作者不收
        self.assertEqual(
            notification_types(self.reviewer_a, 'REJECT').count(), 0)
        self.assertEqual(
            notification_types(self.author, 'REJECT').count(), 0)

    def test_submit_notifies_all_editors(self):
        task = drive_to_submitted(
            self.client, self.editor_a, self.reviewer_a, self.author,
            self.template)
        self.assertEqual(
            notification_types(self.editor_a, 'SUBMIT').count(), 1)
        self.assertEqual(
            notification_types(self.editor_b, 'SUBMIT').count(), 1)
        # 提交的审稿人本人、作者、其他审稿人不收
        self.assertEqual(
            notification_types(self.reviewer_a, 'SUBMIT').count(), 0)
        self.assertEqual(
            notification_types(self.reviewer_b, 'SUBMIT').count(), 0)
        self.assertEqual(
            notification_types(self.author, 'SUBMIT').count(), 0)

    def test_summarize_notifies_all_editors(self):
        task = drive_to_summarized(
            self.client, self.editor_a, self.reviewer_a, self.author,
            self.template)
        self.assertEqual(
            notification_types(self.editor_a, 'SUMMARIZE').count(), 1)
        self.assertEqual(
            notification_types(self.editor_b, 'SUMMARIZE').count(), 1)
        # 汇总不通知作者与审稿人（汇总仅供编辑部决策使用）
        self.assertEqual(
            notification_types(self.author, 'SUMMARIZE').count(), 0)
        self.assertEqual(
            notification_types(self.reviewer_a, 'SUMMARIZE').count(), 0)

    def test_decide_notifies_author(self):
        task = drive_to_summarized(
            self.client, self.editor_a, self.reviewer_a, self.author,
            self.template)
        resp = api_decide(self.client, self.editor_a, task, publish=True)
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(
            notification_types(self.author, 'DECIDE').count(), 1)
        # 决策的编辑、另一位编辑、审稿人均不收 DECIDE
        self.assertEqual(
            notification_types(self.editor_a, 'DECIDE').count(), 0)
        self.assertEqual(
            notification_types(self.editor_b, 'DECIDE').count(), 0)
        self.assertEqual(
            notification_types(self.reviewer_a, 'DECIDE').count(), 0)
        # 无关作者始终零通知
        self.assertEqual(
            notification_types(self.other_author).count(), 0)

    def test_decide_without_publish_still_notifies_author(self):
        """定版裁决 O-1（2026-10-23）：publish=False 时作者仍收 DECIDE 通知
        （只告知决策结果，不含意见详情），编辑部/审稿人不收"""
        task = drive_to_summarized(
            self.client, self.editor_a, self.reviewer_a, self.author,
            self.template)
        resp = api_decide(self.client, self.editor_a, task, publish=False)
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(
            notification_types(self.author, 'DECIDE').count(), 1)
        self.assertEqual(
            notification_types(self.editor_a, 'DECIDE').count(), 0)
        self.assertEqual(
            notification_types(self.reviewer_a, 'DECIDE').count(), 0)

    def test_full_chain_notification_set_per_role(self):
        """全链快照：创建→分配→接受→提交→汇总→终审（publish=True）后，
        每个角色收到的通知类型集合与矩阵一致"""
        task = drive_to_summarized(
            self.client, self.editor_a, self.reviewer_a, self.author,
            self.template)
        resp = api_decide(self.client, self.editor_a, task, publish=True)
        self.assertEqual(resp.status_code, 200)

        def types_of(user):
            return set(
                Notification.objects.filter(user=user)
                .values_list('type', flat=True))

        self.assertEqual(
            types_of(self.author), {'TASK_CREATED', 'DECIDE'})
        self.assertEqual(types_of(self.reviewer_a), {'INVITATION'})
        # 编辑部广播含操作编辑本人：ACCEPT/SUBMIT/SUMMARIZE，不含
        # TASK_CREATED/INVITATION/DECIDE
        self.assertEqual(
            types_of(self.editor_a), {'ACCEPT', 'SUBMIT', 'SUMMARIZE'})
        self.assertEqual(
            types_of(self.editor_b), {'ACCEPT', 'SUBMIT', 'SUMMARIZE'})
        # 无关作者全链零通知
        self.assertEqual(types_of(self.other_author), set())


class NotificationServiceMatrixTests(TestCase):
    """服务级补充格子：REMIND/OVERDUE 接收者与停用编辑过滤"""

    def setUp(self):
        self.editor_a = make_user(
            'mx-editor-a@test.local', ['EDITOR'], '编辑甲')
        self.editor_b = make_user(
            'mx-editor-b@test.local', ['EDITOR'], '编辑乙')
        self.inactive_editor = make_user(
            'mx-editor-off@test.local', ['EDITOR'], '停用编辑',
            is_active=False)
        self.author = make_user(
            'mx-author@test.local', ['AUTHOR'], '作者')
        self.reviewer_a = make_user(
            'mx-ra@test.local', ['REVIEWER'], '审稿人甲')
        self.reviewer_b = make_user(
            'mx-rb@test.local', ['REVIEWER'], '审稿人乙')

    def test_remind_notifies_only_target_reviewer(self):
        task = make_task(self.author, status='REVIEWING')
        assignment = make_assignment(task, self.reviewer_a,
                                     status='REVIEWING')
        NotificationService.send_remind(assignment, days_left=3)

        self.assertEqual(
            notification_types(self.reviewer_a, 'REMIND').count(), 1)
        self.assertEqual(
            notification_types(self.reviewer_b, 'REMIND').count(), 0)
        self.assertEqual(
            notification_types(self.author, 'REMIND').count(), 0)
        self.assertEqual(
            notification_types(self.editor_a, 'REMIND').count(), 0)

    def test_overdue_notifies_reviewer_and_all_editors(self):
        task = make_task(self.author, status='REVIEWING')
        assignment = make_assignment(task, self.reviewer_a,
                                     status='REVIEWING')
        NotificationService.send_overdue(assignment)

        self.assertEqual(
            notification_types(self.reviewer_a, 'OVERDUE').count(), 1)
        self.assertEqual(
            notification_types(self.editor_a, 'OVERDUE').count(), 1)
        self.assertEqual(
            notification_types(self.editor_b, 'OVERDUE').count(), 1)
        # 作者与其他审稿人不收超时通知
        self.assertEqual(
            notification_types(self.author, 'OVERDUE').count(), 0)
        self.assertEqual(
            notification_types(self.reviewer_b, 'OVERDUE').count(), 0)

    def test_accept_skips_inactive_editors(self):
        """编辑部广播过滤 is_active=False：停用编辑不收（现状锁定）"""
        task = make_task(self.author, status='REVIEWING')
        assignment = make_assignment(task, self.reviewer_a)
        NotificationService.send_accept(assignment)

        self.assertEqual(
            notification_types(self.editor_a, 'ACCEPT').count(), 1)
        self.assertEqual(
            notification_types(self.editor_b, 'ACCEPT').count(), 1)
        self.assertEqual(
            notification_types(self.inactive_editor, 'ACCEPT').count(), 0)


class NotificationApiIsolationTests(TestCase):
    """通知 API 用户隔离：列表/未读数/详情/标记已读仅作用于本人通知"""

    def setUp(self):
        self.editor_a = make_user(
            'mx-editor-a@test.local', ['EDITOR'], '编辑甲')
        self.editor_b = make_user(
            'mx-editor-b@test.local', ['EDITOR'], '编辑乙')
        self.author = make_user(
            'mx-author@test.local', ['AUTHOR'], '作者')
        self.task = make_task(self.author, status='REVIEWING')

        Notification.objects.create(
            user=self.author, task=self.task, type='TASK_CREATED',
            title='t1', content='c1', is_read=False)
        Notification.objects.create(
            user=self.author, task=self.task, type='DECIDE',
            title='t2', content='c2', is_read=True)
        Notification.objects.create(
            user=self.editor_a, task=self.task, type='SUBMIT',
            title='t3', content='c3', is_read=False)
        self.client = APIClient()

    def test_list_returns_only_own_notifications(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.get('/api/notifications/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 2)
        self.assertEqual(len(resp.data['results']), 2)
        types = {n['type'] for n in resp.data['results']}
        self.assertEqual(types, {'TASK_CREATED', 'DECIDE'})

        self.client.force_authenticate(user=self.editor_a)
        resp = self.client.get('/api/notifications/')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['type'], 'SUBMIT')

        self.client.force_authenticate(user=self.editor_b)
        resp = self.client.get('/api/notifications/')
        self.assertEqual(resp.data['count'], 0)

    def test_unread_count_isolated(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.get('/api/notifications/unread_count/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['unread_count'], 1)

        self.client.force_authenticate(user=self.editor_a)
        resp = self.client.get('/api/notifications/unread_count/')
        self.assertEqual(resp.data['unread_count'], 1)

        self.client.force_authenticate(user=self.editor_b)
        resp = self.client.get('/api/notifications/unread_count/')
        self.assertEqual(resp.data['unread_count'], 0)

    def test_cannot_retrieve_others_notification(self):
        author_note = Notification.objects.filter(user=self.author).first()
        self.client.force_authenticate(user=self.editor_a)
        resp = self.client.get(
            f'/api/notifications/{author_note.notification_id}/')
        self.assertEqual(resp.status_code, 404)

        # 本人可见
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(
            f'/api/notifications/{author_note.notification_id}/')
        self.assertEqual(resp.status_code, 200)

    def test_mark_read_cannot_touch_others(self):
        author_note = Notification.objects.filter(
            user=self.author, is_read=False).first()
        self.client.force_authenticate(user=self.editor_a)
        resp = self.client.post(
            '/api/notifications/mark_read/',
            {'notification_ids': [author_note.notification_id]},
            format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['updated_count'], 0)

        author_note.refresh_from_db()
        self.assertFalse(author_note.is_read)

        # 本人标记成功
        self.client.force_authenticate(user=self.author)
        resp = self.client.post(
            '/api/notifications/mark_read/',
            {'notification_ids': [author_note.notification_id]},
            format='json')
        self.assertEqual(resp.data['updated_count'], 1)
        author_note.refresh_from_db()
        self.assertTrue(author_note.is_read)
