"""#017 测试补课 —— forms 意见端点 API 测试（决策 #014 提请的测试补课挂账项）

覆盖 apps/forms 意见相关端点的权限与行为断言（只补缺口，不重复
test_p0_idor.py 已覆盖的 task_opinions IDOR/匿名化/编辑部全量基础格）：

- GET  /api/opinions/my_opinion/?task_id=   我的意见（200 有意见 / 404 无 /
  仅审稿人，编辑部与作者 403 / 意见按 reviewer 隔离）
- GET  /api/opinions/task_opinions/?task_id= 作者发布门控补缺：
  未汇总未决策 403、publish=False 403、SUPERSEDED 不入结果
- POST /api/opinions/submit/                提交意见（角色/分配状态门 /
  校验规则 / 草稿转提交 / 状态机自动转换 / 重复提交拒绝）
- POST /api/opinions/save_draft/            草稿保存（新建与更新同一记录 /
  已提交后拒绝 / 宽松校验但评分范围仍校验）
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


def make_task(author, status='REVIEWING', publish=True, **kwargs):
    # 模板须 ≥2 维：FormService.validate_opinion 要求表单维度数量在 2-8
    template = Template.objects.create(
        template_name='意见测试模板', template_type='SYSTEM_DEFAULT',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义'},
            {'dimensionId': 'D2', 'dimensionName': '创新性'},
        ],
    )
    defaults = dict(
        title='意见测试稿件', abstract='摘要', keywords=['a', 'b', 'c'],
        subject_area='经济学', manuscript_type='论文',
        manuscript_file='op-test.pdf', review_mode='SINGLE_BLIND',
        deadline=date.today() + timedelta(days=14),
        template_id=template.template_id, author_user_id=author, status=status,
        publish_opinions_to_author=publish,
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


def make_form(task):
    return ReviewForm.objects.create(
        task=task, template_id=task.template_id,
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义'},
            {'dimensionId': 'D2', 'dimensionName': '创新性'},
        ],
    )


def make_opinion(task, reviewer, status='SUBMITTED', assignment=None):
    form = ReviewForm.objects.filter(task=task).first() or make_form(task)
    assignment = assignment or make_assignment(task, reviewer, status='ACCEPTED')
    return ReviewOpinion.objects.create(
        task=task, form=form, assignment=assignment, reviewer=reviewer,
        dimension_scores=[
            {'dimensionId': 'D1', 'score': 4, 'comment': '扎实'},
            {'dimensionId': 'D2', 'score': 5, 'comment': '新颖'},
        ],
        recommendation='ACCEPT', overall_comment='整体质量不错',
        status=status, submitted_at=timezone.now() if status == 'SUBMITTED' else None,
    )


def valid_submit_payload(task):
    """满足校验的最小合法提交（两维 D1+D2，每维评语≥50字，综合≥100字）"""
    return {
        'task_id': task.task_id,
        'dimension_scores': [
            {'dimensionId': 'D1', 'score': 4, 'comment': '研' * 50},
            {'dimensionId': 'D2', 'score': 5, 'comment': '创' * 50},
        ],
        'recommendation': 'MINOR_REVISION',
        'overall_comment': '评' * 100,
    }


class MyOpinionApiTests(TestCase):
    """my_opinion：200 有意见 / 404 无意见 / 仅审稿人 / reviewer 隔离"""

    def setUp(self):
        self.editor = make_user('op-editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('op-author@test.local', ['AUTHOR'], '作者')
        self.reviewer_a = make_user('op-ra@test.local', ['REVIEWER'], '审稿人甲')
        self.reviewer_b = make_user('op-rb@test.local', ['REVIEWER'], '审稿人乙')
        self.task = make_task(self.author, status='REVIEWING')
        self.client = APIClient()

    def test_reviewer_reads_own_draft(self):
        make_opinion(self.task, self.reviewer_a, status='DRAFT')
        self.client.force_authenticate(user=self.reviewer_a)
        resp = self.client.get(
            '/api/opinions/my_opinion/', {'task_id': self.task.task_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'DRAFT')
        self.assertEqual(resp.data['reviewer'], self.reviewer_a.user_id)

    def test_reviewer_reads_own_submitted(self):
        make_opinion(self.task, self.reviewer_a, status='SUBMITTED')
        self.client.force_authenticate(user=self.reviewer_a)
        resp = self.client.get(
            '/api/opinions/my_opinion/', {'task_id': self.task.task_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'SUBMITTED')
        self.assertIsNotNone(resp.data['submitted_at'])

    def test_no_opinion_returns_404(self):
        """无草稿无提交：404（#015 遗留问题 2 的前端误导 toast 根因）"""
        self.client.force_authenticate(user=self.reviewer_a)
        resp = self.client.get(
            '/api/opinions/my_opinion/', {'task_id': self.task.task_id})
        self.assertEqual(resp.status_code, 404)
        self.assertIn('暂无意见记录', str(resp.data))

    def test_opinions_isolated_between_reviewers(self):
        """审稿人甲查不到审稿人乙的意见（reviewer 过滤）"""
        make_opinion(self.task, self.reviewer_b, status='SUBMITTED')
        self.client.force_authenticate(user=self.reviewer_a)
        resp = self.client.get(
            '/api/opinions/my_opinion/', {'task_id': self.task.task_id})
        self.assertEqual(resp.status_code, 404)

    def test_editor_forbidden(self):
        make_opinion(self.task, self.reviewer_a, status='SUBMITTED')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get(
            '/api/opinions/my_opinion/', {'task_id': self.task.task_id})
        self.assertEqual(resp.status_code, 403)

    def test_author_forbidden(self):
        make_opinion(self.task, self.reviewer_a, status='SUBMITTED')
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(
            '/api/opinions/my_opinion/', {'task_id': self.task.task_id})
        self.assertEqual(resp.status_code, 403)

    def test_missing_task_id_returns_400(self):
        self.client.force_authenticate(user=self.reviewer_a)
        resp = self.client.get('/api/opinions/my_opinion/')
        self.assertEqual(resp.status_code, 400)

    def test_unknown_task_returns_404(self):
        self.client.force_authenticate(user=self.reviewer_a)
        resp = self.client.get(
            '/api/opinions/my_opinion/', {'task_id': 'RT-20990101-9999'})
        self.assertEqual(resp.status_code, 404)


class TaskOpinionsPublishGateTests(TestCase):
    """task_opinions 作者侧发布门控（test_p0_idor 只覆盖了放行格）"""

    def setUp(self):
        self.editor = make_user('op-editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('op-author@test.local', ['AUTHOR'], '作者')
        self.reviewer = make_user('op-ra@test.local', ['REVIEWER'], '审稿人甲')
        self.client = APIClient()

    def test_author_blocked_before_summarized(self):
        """任务未到 SUMMARIZED/DECIDED：作者 403（审稿意见尚未公开）"""
        task = make_task(self.author, status='REVIEWING', publish=True)
        make_opinion(task, self.reviewer, status='SUBMITTED')
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(
            '/api/opinions/task_opinions/', {'task_id': task.task_id})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('尚未公开', str(resp.data))

    def test_author_blocked_when_not_published(self):
        """DECIDED 但 publish_opinions_to_author=False：作者 403"""
        task = make_task(self.author, status='DECIDED', publish=False)
        make_opinion(task, self.reviewer, status='SUBMITTED')
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(
            '/api/opinions/task_opinions/', {'task_id': task.task_id})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('未向作者公开', str(resp.data))

    def test_superseded_opinions_excluded(self):
        """V1.2 严重#10 伴生：SUPERSEDED（回退历史）不入作者可见口径"""
        task = make_task(self.author, status='DECIDED', publish=True)
        make_opinion(task, self.reviewer, status='SUBMITTED')
        make_opinion(task, make_user('op-rb2@test.local', ['REVIEWER'], '审稿人乙'),
                     status='SUPERSEDED')
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(
            '/api/opinions/task_opinions/', {'task_id': task.task_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['status'], 'SUBMITTED')

    def test_editor_unaffected_by_gate(self):
        """编辑部不受发布门控影响（任意任务状态可见全部已提交意见）"""
        task = make_task(self.author, status='REVIEWING', publish=False)
        make_opinion(task, self.reviewer, status='SUBMITTED')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get(
            '/api/opinions/task_opinions/', {'task_id': task.task_id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertFalse(resp.data['is_anonymized'])

    def test_missing_task_id_returns_400(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get('/api/opinions/task_opinions/')
        self.assertEqual(resp.status_code, 400)


class SubmitOpinionApiTests(TestCase):
    """submit：角色/分配状态门 + 校验规则 + 草稿转提交 + 状态机联动"""

    def setUp(self):
        self.editor = make_user('op-editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('op-author@test.local', ['AUTHOR'], '作者')
        self.reviewer = make_user('op-ra@test.local', ['REVIEWER'], '审稿人甲')
        self.other_reviewer = make_user(
            'op-rb@test.local', ['REVIEWER'], '审稿人乙')
        self.task = make_task(self.author, status='REVIEWING')
        self.assignment = make_assignment(self.task, self.reviewer, status='ACCEPTED')
        self.client = APIClient()

    def test_submit_success_creates_submitted_opinion(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], 'SUBMITTED')
        self.assertIsNotNone(resp.data['submitted_at'])

        opinion = ReviewOpinion.objects.get(assignment=self.assignment)
        self.assertEqual(opinion.recommendation, 'MINOR_REVISION')
        self.assertEqual(opinion.overall_comment, '评' * 100)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assignment_status, 'SUBMITTED')

    def test_submit_auto_transitions_task_when_all_submitted(self):
        """单人任务提交后状态机自动 REVIEWING -> SUBMITTED"""
        self.client.force_authenticate(user=self.reviewer)
        self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'SUBMITTED')

    def test_draft_promoted_to_submitted_same_record(self):
        """先存草稿再提交：同一条记录转为 SUBMITTED，不新建"""
        self.client.force_authenticate(user=self.reviewer)
        draft_resp = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id, 'overall_comment': '半成品'},
            format='json')
        self.assertEqual(draft_resp.status_code, 200)
        draft_id = draft_resp.data['opinion']['opinion_id']

        submit_resp = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(submit_resp.status_code, 201)
        self.assertEqual(submit_resp.data['opinion_id'], draft_id)
        self.assertEqual(ReviewOpinion.objects.filter(
            assignment=self.assignment).count(), 1)
        self.assertEqual(ReviewOpinion.objects.get(
            assignment=self.assignment).status, 'SUBMITTED')

    def test_duplicate_submit_rejected(self):
        """重复提交被拒（两道门）：
        正常路径由分配状态门拦截（首次提交后 assignment 已转 SUBMITTED）；
        "不可重复提交"分支仅在状态回退后二次提交时可达（现状锁定）。
        """
        self.client.force_authenticate(user=self.reviewer)
        first = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(second.status_code, 400)

        # 模拟分配状态回退（如任务退回重审）后再次提交：
        # 已有 SUBMITTED 意见时由「不可重复提交」分支拦截
        self.assignment.refresh_from_db()
        self.assignment.assignment_status = 'REVIEWING'
        self.assignment.save()
        third = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(third.status_code, 400)
        self.assertIn('不可重复提交', str(third.data))

    def test_author_forbidden(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(resp.status_code, 403)

    def test_editor_forbidden(self):
        """编辑部也不走 submit（仅审稿人可提交审稿意见）"""
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(resp.status_code, 403)

    def test_reviewer_without_assignment_gets_404(self):
        self.client.force_authenticate(user=self.other_reviewer)
        resp = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(resp.status_code, 404)

    def test_invited_assignment_cannot_submit(self):
        """INVITED（未接受邀请）不允许提交"""
        self.assignment.assignment_status = 'INVITED'
        self.assignment.save()
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(
            '/api/opinions/submit/', valid_submit_payload(self.task),
            format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('不允许提交', str(resp.data))

    def test_validation_missing_dimension(self):
        payload = valid_submit_payload(self.task)
        payload['dimension_scores'] = []
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/opinions/submit/', payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('缺少维度评分', str(resp.data))

    def test_validation_score_out_of_range(self):
        payload = valid_submit_payload(self.task)
        payload['dimension_scores'] = [
            {'dimensionId': 'D1', 'score': 6, 'comment': '研' * 50}]
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/opinions/submit/', payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('不在1-5范围内', str(resp.data))

    def test_validation_comment_too_short(self):
        payload = valid_submit_payload(self.task)
        payload['dimension_scores'] = [
            {'dimensionId': 'D1', 'score': 4, 'comment': '太短'}]
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/opinions/submit/', payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('不足50字', str(resp.data))

    def test_validation_overall_comment_too_short(self):
        payload = valid_submit_payload(self.task)
        payload['overall_comment'] = '太短'
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/opinions/submit/', payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('综合评语不足100字', str(resp.data))

    def test_validation_invalid_recommendation(self):
        payload = valid_submit_payload(self.task)
        payload['recommendation'] = 'MAYBE'
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/opinions/submit/', payload, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_missing_task_id_returns_400(self):
        payload = valid_submit_payload(self.task)
        payload['task_id'] = ''
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/opinions/submit/', payload, format='json')
        self.assertEqual(resp.status_code, 400)


class SaveDraftApiTests(TestCase):
    """save_draft：新建与幂等更新 / 已提交后拒绝 / 宽松校验边界"""

    def setUp(self):
        self.editor = make_user('op-editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('op-author@test.local', ['AUTHOR'], '作者')
        self.reviewer = make_user('op-ra@test.local', ['REVIEWER'], '审稿人甲')
        self.task = make_task(self.author, status='REVIEWING')
        self.assignment = make_assignment(self.task, self.reviewer, status='ACCEPTED')
        self.client = APIClient()

    def test_create_draft_with_partial_data(self):
        """草稿允许部分填写（无维度、无推荐）"""
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id, 'overall_comment': '先写一版'},
            format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['message'], '草稿已保存')
        self.assertEqual(resp.data['opinion']['status'], 'DRAFT')
        self.assertEqual(resp.data['opinion']['overall_comment'], '先写一版')

    def test_resave_updates_same_record(self):
        """重复保存更新同一条草稿，不新增记录"""
        self.client.force_authenticate(user=self.reviewer)
        first = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id, 'overall_comment': '第一版'},
            format='json')
        self.assertEqual(first.status_code, 200)
        draft_id = first.data['opinion']['opinion_id']

        second = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id, 'overall_comment': '第二版'},
            format='json')
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['opinion']['opinion_id'], draft_id)
        self.assertEqual(ReviewOpinion.objects.filter(
            assignment=self.assignment).count(), 1)
        self.assertEqual(ReviewOpinion.objects.get(
            assignment=self.assignment).overall_comment, '第二版')

    def test_cannot_save_draft_after_submitted(self):
        self.assignment.assignment_status = 'SUBMITTED'
        self.assignment.submitted_at = timezone.now()
        self.assignment.save()
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id, 'overall_comment': '迟到的草稿'},
            format='json')
        self.assertEqual(resp.status_code, 400)
        # V1.2 建议#16：状态门扩展后文案口径变更（含状态值）
        self.assertIn('不可保存草稿', str(resp.data))
        self.assertIn('SUBMITTED', str(resp.data))

    def test_draft_still_validates_score_range(self):
        """宽松校验边界：草稿仍校验评分 1-5"""
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id,
             'dimension_scores': [{'dimensionId': 'D1', 'score': 6}],
             'overall_comment': '越界草稿'},
            format='json')
        self.assertEqual(resp.status_code, 400)

    def test_author_forbidden(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_editor_forbidden(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_reviewer_without_assignment_gets_404(self):
        other = make_user('op-rb@test.local', ['REVIEWER'], '审稿人乙')
        self.client.force_authenticate(user=other)
        resp = self.client.post(
            '/api/opinions/save_draft/',
            {'task_id': self.task.task_id}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_missing_task_id_returns_400(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post('/api/opinions/save_draft/', {}, format='json')
        self.assertEqual(resp.status_code, 400)
