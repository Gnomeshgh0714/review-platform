"""状态机与并发提交测试 - 对应 AC-T-04（状态机全覆盖）与 AC-T-14（三人并发提交）"""
import threading
from datetime import date, timedelta

from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase

from apps.forms.models import ReviewForm, ReviewOpinion
from apps.tasks.models import ReviewTask, ReviewAssignment, Template, StateLog
from apps.tasks.state_machine import StateMachineService, StateMachineError
from apps.users.models import User


def make_task(status='PENDING', **kwargs):
    """构造一个可直接使用的审稿任务（含模板与作者）"""
    author = kwargs.pop('author', None) or User.objects.create(
        email='author@test.local', name='作者', roles=['AUTHOR'],
    )
    template = Template.objects.create(
        template_name='测试模板', template_type='SYSTEM_DEFAULT',
        dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
    )
    defaults = dict(
        title='并发测试稿件', abstract='摘要', keywords=[],
        subject_area='经济学', manuscript_type='论文',
        manuscript_file='test.pdf', review_mode='SINGLE_BLIND',
        deadline=date.today() + timedelta(days=14),
        template_id=template.template_id, author_user_id=author, status=status,
    )
    defaults.update(kwargs)
    return ReviewTask.objects.create(**defaults)


def make_assignment(task, reviewer, status='ACCEPTED', deadline=None):
    return ReviewAssignment.objects.create(
        task=task, reviewer=reviewer,
        deadline=deadline or date.today() + timedelta(days=14),
        invitation_expiry=date.today() + timedelta(days=3),
        assignment_status=status,
        assigned_by=None,
    )


class StateMachineValidationTests(TestCase):
    """AC-T-04：合法/非法转换全覆盖"""

    def setUp(self):
        self.editor = User.objects.create(
            email='editor@test.local', name='编辑部', roles=['EDITOR'],
        )

    def test_valid_transition_writes_log_and_bumps_version(self):
        task = make_task(status='PENDING')
        reviewer = User.objects.create(
            email='r@test.local', name='审稿人', roles=['REVIEWER'],
        )
        make_assignment(task, reviewer, status='INVITED')

        updated = StateMachineService.execute_transition(
            task, 'ASSIGNED', self.editor, '测试分配'
        )
        self.assertEqual(updated.status, 'ASSIGNED')
        self.assertEqual(updated.version, 1)
        self.assertTrue(
            StateLog.objects.filter(
                task=task, from_state='PENDING', to_state='ASSIGNED',
                operator_type='EDITOR', operator_user=self.editor,
            ).exists()
        )

    def test_invalid_transition_rejected(self):
        task = make_task(status='PENDING')
        with self.assertRaises(StateMachineError):
            StateMachineService.execute_transition(task, 'DECIDED', self.editor, '跳转')

    def test_assigned_requires_assignment_record(self):
        task = make_task(status='PENDING')  # 无任何分配记录
        with self.assertRaises(StateMachineError):
            StateMachineService.execute_transition(task, 'ASSIGNED', self.editor, '无分配')

    def test_reviewing_requires_accepted_reviewer(self):
        task = make_task(status='ASSIGNED')
        reviewer = User.objects.create(
            email='r@test.local', name='审稿人', roles=['REVIEWER'],
        )
        make_assignment(task, reviewer, status='INVITED')  # 仅邀请未接受
        with self.assertRaises(StateMachineError):
            StateMachineService.execute_transition(task, 'REVIEWING', self.editor, '无人接受')

    def test_submitted_requires_all_submitted_unless_forced(self):
        task = make_task(status='REVIEWING')
        r1 = User.objects.create(email='r1@test.local', name='审1', roles=['REVIEWER'])
        r2 = User.objects.create(email='r2@test.local', name='审2', roles=['REVIEWER'])
        make_assignment(task, r1, status='SUBMITTED')
        make_assignment(task, r2, status='ACCEPTED')  # 未提交

        with self.assertRaises(StateMachineError):
            StateMachineService.execute_transition(task, 'SUBMITTED', self.editor, '普通提交')
        # 以「强制」开头的理由放行（编辑强制汇总）
        updated = StateMachineService.execute_transition(
            task, 'SUBMITTED', self.editor, '强制汇总'
        )
        self.assertEqual(updated.status, 'SUBMITTED')

    def test_all_rejected_rolls_back_to_pending(self):
        task = make_task(status='ASSIGNED')
        reviewer = User.objects.create(
            email='r@test.local', name='审稿人', roles=['REVIEWER'],
        )
        make_assignment(task, reviewer, status='REJECTED')
        updated = StateMachineService.handle_all_rejected(task, self.editor)
        self.assertEqual(updated.status, 'PENDING')

    def test_increment_retry_count_notifies_after_threshold(self):
        from apps.notifications.models import Notification
        task = make_task(status='PENDING')
        for expected in range(1, 5):
            count = StateMachineService.increment_retry_count(task)
            self.assertEqual(count, expected)
        # 第4次重试（>3）应触发「分配困难」通知主编（编辑部用户）
        task.refresh_from_db()
        self.assertEqual(task.retry_count, 4)
        notified = Notification.objects.filter(
            task=task, title__startswith='【分配困难】',
        ).count()
        self.assertGreaterEqual(notified, 1)


class ConcurrentSubmitTests(TransactionTestCase):
    """AC-T-14：三位审稿人并发提交，任务恰好发生一次 REVIEWING -> SUBMITTED 转换

    使用 TransactionTestCase（真实提交），每个线程独立数据库连接，
    依赖 StateMachineService.check_and_transition_on_submit 的
    select_for_update 行锁保证只有一个线程完成状态转换。
    """

    REVIEWER_COUNT = 3

    def setUp(self):
        self.editor = User.objects.create(
            email='editor@test.local', name='编辑部', roles=['EDITOR'],
        )
        self.task = make_task(status='REVIEWING')
        self.template = Template.objects.get(
            template_id=self.task.template_id,
        )
        self.form = ReviewForm.objects.create(
            task=self.task, template=self.template,
            template_snapshot={}, dimensions=self.template.dimensions,
        )
        self.assignments = []
        for i in range(self.REVIEWER_COUNT):
            reviewer = User.objects.create(
                email=f'r{i}@test.local', name=f'审稿人{i}', roles=['REVIEWER'],
            )
            self.assignments.append(make_assignment(self.task, reviewer, status='ACCEPTED'))

    def _submit_in_thread(self, assignment, barrier, errors):
        """模拟审稿人提交：建意见 + 更新分配 + 触发状态机检查（与 submit 视图同一原子块）"""
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            with transaction.atomic():
                ReviewOpinion.objects.create(
                    task=self.task, form=self.form, assignment=assignment,
                    reviewer=assignment.reviewer,
                    dimension_scores=[{'dimensionId': 'D1', 'score': 4, 'comment': 'ok'}],
                    recommendation='MINOR_REVISION',
                    overall_comment='综合评语' * 20,
                    status='SUBMITTED', round=1,
                )
                assignment.assignment_status = 'SUBMITTED'
                assignment.save()
                StateMachineService.check_and_transition_on_submit(self.task)
        except Exception as e:  # noqa: BLE001 - 线程异常需带回主线程断言
            errors.append((assignment.assignment_id, repr(e)))
        finally:
            close_old_connections()

    def test_concurrent_submit_single_transition(self):
        barrier = threading.Barrier(self.REVIEWER_COUNT)
        errors = []
        threads = [
            threading.Thread(target=self._submit_in_thread, args=(a, barrier, errors))
            for a in self.assignments
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertFalse(any(t.is_alive() for t in threads), '并发线程未在超时内完成')
        self.assertEqual(errors, [], f'并发提交线程出现异常: {errors}')

        # 全部分配记录均为 SUBMITTED
        for a in self.assignments:
            a.refresh_from_db()
            self.assertEqual(a.assignment_status, 'SUBMITTED')

        # 任务转为 SUBMITTED，且仅发生一次转换（version 恰好 +1）
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'SUBMITTED')
        self.assertEqual(self.task.version, 1)

        # 恰好 1 条系统自动转换日志，无重复
        logs = StateLog.objects.filter(
            task=self.task, from_state='REVIEWING', to_state='SUBMITTED',
            operator_type='SYSTEM',
        )
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().trigger_reason,
                         '全部已接受审稿人均提交意见，系统自动转换')

        # 每位审稿人恰好 1 份已提交意见
        for a in self.assignments:
            self.assertEqual(
                ReviewOpinion.objects.filter(assignment=a, status='SUBMITTED').count(), 1,
            )

    def test_partial_submit_keeps_reviewing(self):
        """仅部分提交时任务应保持 REVIEWING"""
        a = self.assignments[0]
        with transaction.atomic():
            ReviewOpinion.objects.create(
                task=self.task, form=self.form, assignment=a,
                reviewer=a.reviewer,
                dimension_scores=[{'dimensionId': 'D1', 'score': 4, 'comment': 'ok'}],
                recommendation='ACCEPT',
                overall_comment='综合评语' * 20,
                status='SUBMITTED', round=1,
            )
            a.assignment_status = 'SUBMITTED'
            a.save()
            StateMachineService.check_and_transition_on_submit(self.task)

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'REVIEWING')
