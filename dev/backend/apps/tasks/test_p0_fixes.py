"""P0修复回归测试 - 数据落地三件套 + 双盲保护
（对应评审意见 V1.1 致命#3/#5/#6/#7）

覆盖：
- make_decision：决策字段先落库再转状态（execute_transition 重取行不再丢内存字段）
- make_decision：自动触发知识库归档（PRD §5.3.1）
- force_summarize：AC-T-11 三要素（原因必填 / ≥1 已提交意见 / 未提交者标 EXPIRED）
- ReviewTaskSerializer.to_representation：作者不见审稿人身份、双盲审稿人不见作者身份
"""
from datetime import date, timedelta

from django.utils import timezone

from rest_framework.test import APIClient

from django.test import TestCase

from apps.forms.models import ReviewForm, ReviewOpinion
from apps.tasks.models import ReviewTask, Template, ReviewAssignment
from apps.users.models import User


def make_user(email, roles, name):
    return User.objects.create(email=email, name=name, roles=roles)


def make_task(author, status='PENDING', review_mode='SINGLE_BLIND', **kwargs):
    template = Template.objects.create(
        template_name='测试模板', template_type='SYSTEM_DEFAULT',
        dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
    )
    defaults = dict(
        title='测试稿件', abstract='摘要', keywords=['a', 'b', 'c'],
        subject_area='经济学', manuscript_type='论文',
        manuscript_file='test.pdf', review_mode=review_mode,
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


def make_submitted_opinion(task, reviewer):
    form = ReviewForm.objects.create(
        task=task, template_id=task.template_id,
        dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
    )
    assignment = ReviewAssignment.objects.filter(
        task=task, reviewer=reviewer,
    ).first() or make_assignment(task, reviewer, status='SUBMITTED')
    assignment.assignment_status = 'SUBMITTED'
    assignment.submitted_at = timezone.now()
    assignment.save()
    return ReviewOpinion.objects.create(
        task=task, form=form, assignment=assignment, reviewer=reviewer,
        dimension_scores=[{'dimensionId': 'D1', 'score': 4, 'comment': '扎实'}],
        recommendation='ACCEPT', overall_comment='整体质量不错',
        status='SUBMITTED', submitted_at=timezone.now(),
    )


class MakeDecisionPersistenceTests(TestCase):
    """致命#6：决策字段必须真实落库"""

    def setUp(self):
        self.editor = make_user('editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('author@test.local', ['AUTHOR'], '作者甲')
        self.task = make_task(self.author, status='SUMMARIZED')
        self.client = APIClient()
        self.client.force_authenticate(user=self.editor)

    def test_decision_fields_persist_in_db(self):
        notes = '本稿件研究问题明确、方法可靠，两位审稿人意见积极，符合接收标准。' * 4
        resp = self.client.post(
            f'/api/tasks/{self.task.task_id}/make_decision/',
            {'decision': 'ACCEPT', 'notes': notes, 'publish': True}, format='json',
        )
        self.assertEqual(resp.status_code, 200)

        # 重新从数据库读取：修复前此处为空串（内存对象被序列化、DB 未落库）
        self.task.refresh_from_db()
        self.assertEqual(self.task.final_decision, 'ACCEPT')
        self.assertEqual(self.task.decision_notes, notes)
        self.assertTrue(self.task.publish_opinions_to_author)
        self.assertEqual(self.task.status, 'DECIDED')

        # 再经 GET 接口验证对外可见（修复前 E2E 被内存序列化欺骗的教训）
        resp = self.client.get(f'/api/tasks/{self.task.task_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['final_decision'], 'ACCEPT')
        self.assertEqual(resp.data['decision_notes'], notes)

    def test_decision_triggers_knowledge_archive(self):
        """致命#7：DECIDED 后自动生成第一阶段匿名化归档"""
        notes = '本稿件研究问题明确、方法可靠，两位审稿人意见积极，符合接收标准。' * 4
        resp = self.client.post(
            f'/api/tasks/{self.task.task_id}/make_decision/',
            {'decision': 'ACCEPT', 'notes': notes, 'publish': True}, format='json',
        )
        self.assertEqual(resp.status_code, 200)

        from apps.knowledge.models import KnowledgeItem
        self.assertTrue(
            KnowledgeItem.objects.filter(source_task_id=self.task.task_id).exists()
        )

    def test_decision_twice_rejected(self):
        notes = '本稿件研究问题明确、方法可靠，两位审稿人意见积极，符合接收标准。' * 4
        self.client.post(
            f'/api/tasks/{self.task.task_id}/make_decision/',
            {'decision': 'ACCEPT', 'notes': notes}, format='json',
        )
        resp = self.client.post(
            f'/api/tasks/{self.task.task_id}/make_decision/',
            {'decision': 'REJECT', 'notes': notes}, format='json',
        )
        self.assertEqual(resp.status_code, 400)  # 已 DECIDED，不允许再次决策


class ForceSummarizeTests(TestCase):
    """致命#3：force_summarize 500 + AC-T-11 要素补全"""

    def setUp(self):
        self.editor = make_user('editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('author@test.local', ['AUTHOR'], '作者甲')
        self.reviewer_a = make_user('ra@test.local', ['REVIEWER'], '审稿人甲')
        self.reviewer_b = make_user('rb@test.local', ['REVIEWER'], '审稿人乙')
        self.client = APIClient()
        self.client.force_authenticate(user=self.editor)

    def _reviewing_task_with_one_submitted(self):
        task = make_task(self.author, status='REVIEWING')
        make_submitted_opinion(task, self.reviewer_a)   # 已提交
        make_assignment(task, self.reviewer_b, status='ACCEPTED')  # 未提交
        return task

    def test_missing_reason_rejected(self):
        task = self._reviewing_task_with_one_submitted()
        resp = self.client.post(
            f'/api/tasks/{task.task_id}/force_summarize/', {}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_no_submitted_opinion_rejected(self):
        task = make_task(self.author, status='REVIEWING')
        make_assignment(task, self.reviewer_a, status='ACCEPTED')
        resp = self.client.post(
            f'/api/tasks/{task.task_id}/force_summarize/',
            {'reason': '时间紧迫'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_force_summarize_marks_stragglers_expired(self):
        """AC-T-11：未提交审稿人置 EXPIRED，状态转 SUBMITTED，全程无 500"""
        task = self._reviewing_task_with_one_submitted()
        resp = self.client.post(
            f'/api/tasks/{task.task_id}/force_summarize/',
            {'reason': '剩余审稿人长期未响应'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['marked_expired'], 1)
        self.assertEqual(resp.data['submitted_opinions'], 1)

        task.refresh_from_db()
        self.assertEqual(task.status, 'SUBMITTED')

        statuses = {
            a.reviewer.user_id: a.assignment_status
            for a in task.assignments.all()
        }
        self.assertEqual(statuses[self.reviewer_a.user_id], 'SUBMITTED')
        self.assertEqual(statuses[self.reviewer_b.user_id], 'EXPIRED')

    def test_force_summarize_requires_reviewing_status(self):
        task = make_task(self.author, status='PENDING')
        resp = self.client.post(
            f'/api/tasks/{task.task_id}/force_summarize/',
            {'reason': '越权尝试'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_force_summarize_editor_only(self):
        task = self._reviewing_task_with_one_submitted()
        self.client.force_authenticate(user=self.reviewer_b)
        resp = self.client.post(
            f'/api/tasks/{task.task_id}/force_summarize/',
            {'reason': '审稿人不应可触发'}, format='json')
        self.assertEqual(resp.status_code, 403)


class DoubleBlindSerializationTests(TestCase):
    """致命#5：AC-T-13 双盲身份字段裁剪"""

    def setUp(self):
        self.editor = make_user('editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('author@test.local', ['AUTHOR'], '作者甲')
        self.reviewer = make_user('reviewer@test.local', ['REVIEWER'], '审稿人甲')
        self.client = APIClient()

    def _assigned_task(self, review_mode):
        task = make_task(self.author, status='REVIEWING', review_mode=review_mode)
        make_assignment(task, self.reviewer, status='ACCEPTED')
        return task

    def test_author_never_sees_reviewer_identity(self):
        """作者视角：任何模式（含单盲）下不可见审稿人身份"""
        for mode in ('SINGLE_BLIND', 'DOUBLE_BLIND'):
            task = self._assigned_task(mode)
            self.client.force_authenticate(user=self.author)
            resp = self.client.get('/api/tasks/my_articles/')
            self.assertEqual(resp.status_code, 200)
            mine = [t for t in resp.data['results'] if t['task_id'] == task.task_id]
            self.assertEqual(len(mine), 1)
            for assignment in mine[0]['assignments']:
                for key in ('reviewer', 'reviewer_name', 'reviewer_email',
                            'reviewer_research_areas'):
                    self.assertNotIn(key, assignment,
                                     f'{mode} 模式下作者不应看到 {key}')

    def test_reviewer_blind_to_author_in_double_blind(self):
        task = self._assigned_task('DOUBLE_BLIND')
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get(f'/api/tasks/{task.task_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('author_name', resp.data)
        self.assertNotIn('author_email', resp.data)
        # 任务本身仍可见（审稿工作所需）
        self.assertEqual(resp.data['task_id'], task.task_id)

    def test_reviewer_sees_author_in_single_blind(self):
        task = self._assigned_task('SINGLE_BLIND')
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get(f'/api/tasks/{task.task_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['author_name'], '作者甲')

    def test_editor_sees_everything(self):
        task = self._assigned_task('DOUBLE_BLIND')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get(f'/api/tasks/{task.task_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['author_name'], '作者甲')
        self.assertEqual(
            resp.data['assignments'][0]['reviewer_name'], '审稿人甲')


class StateLogsAnonymizationTests(TestCase):
    """双盲补充（P1批次新增）：state_logs 中审稿人操作者对非编辑部脱敏

    StateLog.operator_type 对任何登录操作者都写 'EDITOR'，
    因此需按 operator_user_id 是否为该任务分配的审稿人来判定脱敏。
    """

    def setUp(self):
        self.editor = make_user('editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('author@test.local', ['AUTHOR'], '作者甲')
        self.reviewer = make_user('reviewer@test.local', ['REVIEWER'], '审稿人甲')
        self.client = APIClient()

    def _task_with_reviewer_log(self):
        """审稿人接受邀请 → 产生 operator=reviewer 的 StateLog"""
        task = make_task(self.author, status='ASSIGNED')
        make_assignment(task, self.reviewer, status='INVITED')
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(
            f'/api/tasks/{task.task_id}/accept_invitation/', {}, format='json')
        self.assertEqual(resp.status_code, 200)
        return task

    def test_author_sees_anonymized_reviewer_operator(self):
        task = self._task_with_reviewer_log()
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(f'/api/tasks/{task.task_id}/state_logs/')
        self.assertEqual(resp.status_code, 200)
        names = {log['operator_name'] for log in resp.data}
        self.assertNotIn('审稿人甲', names)
        self.assertIn('审稿人', names)

    def test_editor_sees_real_reviewer_operator(self):
        task = self._task_with_reviewer_log()
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get(f'/api/tasks/{task.task_id}/state_logs/')
        self.assertEqual(resp.status_code, 200)
        names = {log['operator_name'] for log in resp.data}
        self.assertIn('审稿人甲', names)

    def test_non_participant_author_gets_404(self):
        """无关作者不可见他人任务的状态日志（queryset 归属过滤）"""
        task = self._task_with_reviewer_log()
        other = make_user('other@test.local', ['AUTHOR'], '作者乙')
        self.client.force_authenticate(user=other)
        resp = self.client.get(f'/api/tasks/{task.task_id}/state_logs/')
        self.assertEqual(resp.status_code, 404)
