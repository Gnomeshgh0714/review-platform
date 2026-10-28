"""P2 收官批测试 - AI 审稿异步化（决策 #026，F-3）

覆盖：
1. job 状态机全生命周期（PENDING -> RUNNING -> SUCCEEDED / FAILED）
2. 未配 API Key 时 job FAILED 且 error 落库
3. 工作线程 DB 连接关闭纪律（close_old_connections）
4. 提交端点 201 受理口径与校验链回归（原同步链路的权限门原样保留）
5. 状态端点本人可查 / 越权 403 / 参数与 404
6. process_scheduled 超时清扫段（PENDING/RUNNING 超 5 分钟置 FAILED）

LLM 调用全部 mock（patch AIReviewService），不发真实网络请求。
需要真实跨线程可见数据的用例使用 TransactionTestCase
（参照 apps/tasks/tests.py ConcurrentSubmitTests 的既有口径）。
"""
import threading
import time
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.forms.models import AIReviewJob
from apps.tasks.models import ReviewTask, ReviewAssignment, Template
from apps.users.models import User


def make_user(email, roles, name):
    return User.objects.create(email=email, name=name, roles=roles)


def make_template(name):
    return Template.objects.create(
        template_name=name, template_type='SYSTEM_DEFAULT',
        dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
    )


def make_task(author, status='REVIEWING'):
    template = make_template(f'模板-{author.name}')
    return ReviewTask.objects.create(
        title='AI 审稿异步化测试稿', abstract='摘要', keywords=['关键词'],
        subject_area='经济学', manuscript_type='论文',
        manuscript_file='test.pdf', review_mode='DOUBLE_BLIND',
        deadline=date.today() + timedelta(days=14),
        template_id=template.template_id, author_user_id=author,
        status=status,
    )


def make_assignment(task, reviewer, status='ACCEPTED'):
    return ReviewAssignment.objects.create(
        task=task, reviewer=reviewer,
        deadline=date.today() + timedelta(days=14),
        invitation_expiry=date.today() + timedelta(days=3),
        assignment_status=status,
    )


def fake_review_result():
    return {
        'dimension_scores': [
            {'dimensionId': 'SIGNIFICANCE', 'score': 4, 'comment': '研究意义评语' * 10},
        ],
        'recommendation': 'MINOR_REVISION',
        'overall_comment': '综合评语' * 30,
        'suggestions': ['补充稳健性检验'],
    }


def run_job_in_thread(job_id):
    """与线程池执行方式一致：独立线程跑 run_ai_review_job 并等待结束。"""
    t = threading.Thread(target=_target, args=(job_id,))
    t.start()
    t.join(timeout=10)


def _target(job_id):
    from apps.forms.ai_jobs import run_ai_review_job
    run_ai_review_job(job_id)


def wait_for_terminal(job_id, timeout=10):
    """轮询等待 job 到终态（SUCCEEDED/FAILED），超时返回最后一态。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = AIReviewJob.objects.get(job_id=job_id)
        if job.status in ('SUCCEEDED', 'FAILED'):
            return job
        time.sleep(0.05)
    return AIReviewJob.objects.get(job_id=job_id)


# ======================================================================
# 1. job 全生命周期状态机（工作线程内执行，mock generate_review）
# ======================================================================
class AIReviewJobLifecycleTests(TransactionTestCase):
    """run_ai_review_job 状态机：PENDING -> RUNNING -> SUCCEEDED/FAILED。

    TransactionTestCase：工作线程独立数据库连接，任务行需真实提交可见
    （TestCase 的事务包裹对其他连接不可见，参照 ConcurrentSubmitTests）。
    """

    def setUp(self):
        self.author = make_user('author@test.local', ['AUTHOR'], '作者')
        self.reviewer = make_user('r@test.local', ['REVIEWER'], '审稿人')
        self.task = make_task(self.author)
        self.client = APIClient()

    def _make_job(self):
        return AIReviewJob.objects.create(task=self.task, reviewer=self.reviewer)

    def test_job_succeeds_writes_result(self):
        job = self._make_job()
        self.assertEqual(job.status, 'PENDING')
        self.assertIsNone(job.result)

        with mock.patch(
            'apps.forms.ai_review.AIReviewService.generate_review',
            return_value=fake_review_result(),
        ):
            run_job_in_thread(job.job_id)

        job.refresh_from_db()
        self.assertEqual(job.status, 'SUCCEEDED')
        self.assertEqual(job.result['recommendation'], 'MINOR_REVISION')
        self.assertEqual(
            job.result['dimension_scores'][0]['dimensionId'], 'SIGNIFICANCE',
        )
        self.assertEqual(job.error, '')
        self.assertIsNotNone(job.finished_at)

    def test_job_failure_writes_error(self):
        job = self._make_job()

        with mock.patch(
            'apps.forms.ai_review.AIReviewService.generate_review',
            side_effect=ValueError('LLM API 调用失败 (HTTP 429)'),
        ):
            run_job_in_thread(job.job_id)

        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILED')
        self.assertIn('HTTP 429', job.error)
        self.assertIsNone(job.result)
        self.assertIsNotNone(job.finished_at)

    def test_missing_api_key_fails_job_with_error(self):
        """未配置 REVIEWER_LLM_API_KEY：job 置 FAILED 且原始报错落库。"""
        job = self._make_job()

        with mock.patch('apps.forms.ai_review.LLM_API_KEY', ''):
            with mock.patch(
                'apps.forms.ai_review.AIReviewService.extract_pdf_text',
                return_value='论文正文' * 100,
            ):
                run_job_in_thread(job.job_id)

        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILED')
        self.assertIn('未配置 REVIEWER_LLM_API_KEY', job.error)
        self.assertIsNotNone(job.finished_at)

    def test_worker_closes_db_connection_on_success_and_failure(self):
        """关键技术纪律：线程收尾必须 close_old_connections（含异常路径）。"""
        ok_job = self._make_job()
        bad_job = self._make_job()

        with mock.patch('apps.forms.ai_jobs.close_old_connections') as close_spy:
            with mock.patch(
                'apps.forms.ai_review.AIReviewService.generate_review',
                return_value=fake_review_result(),
            ):
                run_job_in_thread(ok_job.job_id)
            with mock.patch(
                'apps.forms.ai_review.AIReviewService.generate_review',
                side_effect=ValueError('boom'),
            ):
                run_job_in_thread(bad_job.job_id)

            # 每次执行调用 2 次（进入清理 + finally 收尾），两条路径共 4 次
            self.assertGreaterEqual(close_spy.call_count, 4)

        ok_job.refresh_from_db()
        bad_job.refresh_from_db()
        self.assertEqual(ok_job.status, 'SUCCEEDED')
        self.assertEqual(bad_job.status, 'FAILED')


# ======================================================================
# 2. 提交端点与状态端点（校验链回归 + 受理口径 + 越权）
# ======================================================================
class AIReviewJobApiTests(TestCase):
    """POST ai_review 受理口径（提交函数 mock 为 no-op，不起线程）与
    GET ai_review_status 权限门。原同步链路的校验链（权限门+分配校验）
    在异步化后原样保留，此处为回归。"""

    def setUp(self):
        self.author = make_user('author@test.local', ['AUTHOR'], '作者')
        self.editor = make_user('editor@test.local', ['EDITOR'], '编辑部')
        self.reviewer = make_user('r@test.local', ['REVIEWER'], '审稿人甲')
        self.other_reviewer = make_user('r2@test.local', ['REVIEWER'], '审稿人乙')
        self.task = make_task(self.author)
        self.assignment = make_assignment(self.task, self.reviewer)
        self.client = APIClient()

    def _submit(self, user, task_id=None):
        self.client.force_authenticate(user=user)
        return self.client.post(
            '/api/forms/ai_review/',
            {'task_id': task_id or self.task.task_id},
            format='json',
        )

    def test_submit_creates_job_and_returns_201(self):
        with mock.patch('apps.forms.ai_jobs.submit_ai_review_job') as submit_mock:
            resp = self._submit(self.reviewer)

        self.assertEqual(resp.status_code, 201)
        job_id = resp.data['job_id']
        self.assertTrue(job_id.startswith(f'AIR-{timezone.now().strftime("%Y%m%d")}-'))
        # 受理口径：返回 job_id + 初始状态（PENDING），不再返回审稿结果
        self.assertIn(resp.data['status'], ('PENDING', 'RUNNING'))
        submit_mock.assert_called_once()
        job = AIReviewJob.objects.get(job_id=job_id)
        self.assertEqual(job.task_id, self.task.task_id)
        self.assertEqual(job.reviewer_id, self.reviewer.user_id)
        self.assertEqual(job.status, 'PENDING')

    def test_submit_rejects_author(self):
        resp = self._submit(self.author)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(AIReviewJob.objects.count(), 0)

    def test_submit_rejects_reviewer_without_assignment(self):
        resp = self._submit(self.other_reviewer)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(AIReviewJob.objects.count(), 0)

    def test_submit_rejects_invited_assignment(self):
        self.assignment.assignment_status = 'INVITED'
        self.assignment.save(update_fields=['assignment_status'])
        resp = self._submit(self.reviewer)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AIReviewJob.objects.count(), 0)

    def test_status_owner_reads_result(self):
        job = AIReviewJob.objects.create(
            task=self.task, reviewer=self.reviewer,
            status='SUCCEEDED', result=fake_review_result(),
            finished_at=timezone.now(),
        )
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get(
            '/api/forms/ai_review_status/', {'job_id': job.job_id})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['job_id'], job.job_id)
        self.assertEqual(resp.data['status'], 'SUCCEEDED')
        self.assertEqual(
            resp.data['result']['dimension_scores'][0]['dimensionId'],
            'SIGNIFICANCE',
        )

    def test_status_rejects_other_user(self):
        """越权：他人（含编辑部）查他人 job 一律 403。"""
        job = AIReviewJob.objects.create(
            task=self.task, reviewer=self.reviewer, status='RUNNING',
        )
        for user in (self.other_reviewer, self.editor):
            self.client.force_authenticate(user=user)
            resp = self.client.get(
                '/api/forms/ai_review_status/', {'job_id': job.job_id})
            self.assertEqual(resp.status_code, 403, msg=f'user={user.email}')

    def test_status_missing_param_and_unknown_job(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get('/api/forms/ai_review_status/')
        self.assertEqual(resp.status_code, 400)
        resp = self.client.get(
            '/api/forms/ai_review_status/', {'job_id': 'AIR-20260101-9999'})
        self.assertEqual(resp.status_code, 404)


# ======================================================================
# 3. 提交 -> 线程池执行 -> 轮询终态 全链路
# ======================================================================
class AIReviewSubmitFlowTests(TransactionTestCase):
    """POST 受理后经真实模块级线程池执行，轮询至 SUCCEEDED 取结果。"""

    def setUp(self):
        self.author = make_user('author@test.local', ['AUTHOR'], '作者')
        self.reviewer = make_user('r@test.local', ['REVIEWER'], '审稿人')
        self.task = make_task(self.author)
        make_assignment(self.task, self.reviewer)
        self.client = APIClient()

    def test_full_flow_submit_poll_succeed(self):
        self.client.force_authenticate(user=self.reviewer)

        with mock.patch(
            'apps.forms.ai_review.AIReviewService.generate_review',
            return_value=fake_review_result(),
        ):
            resp = self.client.post(
                '/api/forms/ai_review/',
                {'task_id': self.task.task_id}, format='json',
            )
            self.assertEqual(resp.status_code, 201)
            job_id = resp.data['job_id']

            job = wait_for_terminal(job_id)
            self.assertEqual(job.status, 'SUCCEEDED')

            status_resp = self.client.get(
                '/api/forms/ai_review_status/', {'job_id': job_id})
            self.assertEqual(status_resp.status_code, 200)
            self.assertEqual(status_resp.data['status'], 'SUCCEEDED')
            self.assertEqual(
                status_resp.data['result']['recommendation'], 'MINOR_REVISION',
            )

    def test_full_flow_without_api_key_fails(self):
        self.client.force_authenticate(user=self.reviewer)

        with mock.patch('apps.forms.ai_review.LLM_API_KEY', ''):
            with mock.patch(
                'apps.forms.ai_review.AIReviewService.extract_pdf_text',
                return_value='论文正文' * 100,
            ):
                resp = self.client.post(
                    '/api/forms/ai_review/',
                    {'task_id': self.task.task_id}, format='json',
                )
                self.assertEqual(resp.status_code, 201)

                job = wait_for_terminal(resp.data['job_id'])
                self.assertEqual(job.status, 'FAILED')
                self.assertIn('未配置 REVIEWER_LLM_API_KEY', job.error)


# ======================================================================
# 4. process_scheduled 超时清扫段
# ======================================================================
class AIJobSweepTests(TestCase):

    def setUp(self):
        self.author = make_user('author@test.local', ['AUTHOR'], '作者')
        self.reviewer = make_user('r@test.local', ['REVIEWER'], '审稿人')
        self.task = make_task(self.author)

    def _make_job(self, status):
        job = AIReviewJob.objects.create(
            task=self.task, reviewer=self.reviewer, status=status,
        )
        return job

    def _run_sweep(self):
        from apps.tasks.management.commands.process_scheduled import Command
        stats = {'ai_jobs_swept': 0}
        Command()._sweep_stale_ai_jobs(stats)
        return stats

    def test_sweep_marks_stale_jobs_failed(self):
        """PENDING/RUNNING 超过 5 分钟 -> FAILED，error 写「任务超时清扫」。"""
        stale_pending = self._make_job('PENDING')
        stale_running = self._make_job('RUNNING')
        # auto_now_add 不接受显式赋值，用 update 回拨创建时间到 6 分钟前
        six_min_ago = timezone.now() - timedelta(minutes=6)
        AIReviewJob.objects.filter(
            job_id__in=[stale_pending.job_id, stale_running.job_id],
        ).update(created_at=six_min_ago)

        stats = self._run_sweep()

        self.assertEqual(stats['ai_jobs_swept'], 2)
        for job_id in (stale_pending.job_id, stale_running.job_id):
            job = AIReviewJob.objects.get(job_id=job_id)
            self.assertEqual(job.status, 'FAILED')
            self.assertEqual(job.error, '任务超时清扫')
            self.assertIsNotNone(job.finished_at)

    def test_sweep_keeps_fresh_and_terminal_jobs(self):
        """5 分钟内的中间态与已终态的 job 不被清扫。"""
        fresh_running = self._make_job('RUNNING')
        done = self._make_job('SUCCEEDED')
        AIReviewJob.objects.filter(job_id=done.job_id).update(
            created_at=timezone.now() - timedelta(minutes=30),
        )

        stats = self._run_sweep()

        self.assertEqual(stats['ai_jobs_swept'], 0)
        fresh_running.refresh_from_db()
        done.refresh_from_db()
        self.assertEqual(fresh_running.status, 'RUNNING')
        self.assertEqual(done.status, 'SUCCEEDED')
