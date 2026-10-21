"""
定时任务命令 - T-19 超时与重试处理（ scheduled 部分）

技术实施方案 T-19 要求 Celery 定时任务覆盖：
1. 截止前 7/3/1 天提醒（给审稿人）
2. 邀请超时检测（invitation_expiry 过期 -> EXPIRED，全部过期则回退 PENDING）
3. 审稿超时检测（deadline 过期 -> OVERDUE，全部到期后通知编辑部三选一）
4. 48小时自动通知主编（分配困难任务，S-02）

实现说明（对应决策日志 T-19 降级决策）：
未引入 Celery/Redis 运行时，改为单次执行的管理命令，由 cron/launchd 每日调度：
    0 8 * * *  cd <backend目录> && <.venv>/bin/python manage.py process_scheduled

编辑三选一处理（强制汇总/回退待分配/重新分配）仍走既有的
POST /api/tasks/<id>/handle_overdue/ 接口，本命令只做检测与通知，不做状态机代决。
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import NotificationService
from apps.tasks.models import ReviewTask, ReviewAssignment
from apps.tasks.state_machine import StateMachineService

logger = logging.getLogger(__name__)

REMIND_DAYS_BEFORE = (7, 3, 1)  # 截止前第 7/3/1 天提醒
NOTIFY_EDITOR_INTERVAL = timedelta(hours=48)  # S-02: 分配困难 48 小时未处理再通知


class Command(BaseCommand):
    help = ('T-19 定时任务：截止提醒(7/3/1天)、邀请超时检测、审稿超时检测、'
            '48小时分配困难通知主编。建议 cron 每日执行一次。')

    def handle(self, *args, **options):
        today = timezone.now().date()
        stats = {
            'reminders_sent': 0,
            'invitations_expired': 0,
            'tasks_rolled_back': 0,
            'assignments_overdue': 0,
            'tasks_awaiting_editor': 0,
            'chief_notified': 0,
        }

        self._expire_invitations(today, stats)
        self._send_deadline_reminders(today, stats)
        self._mark_overdue(today, stats)
        self._notify_editor_in_chief(stats)

        self.stdout.write(self.style.SUCCESS(
            'T-19 定时任务完成：'
            f'截止提醒 {stats["reminders_sent"]} 条 | '
            f'邀请过期 {stats["invitations_expired"]} 条 | '
            f'任务回退 {stats["tasks_rolled_back"]} 个 | '
            f'审稿超时 {stats["assignments_overdue"]} 条 | '
            f'待编辑部处理通知 {stats["tasks_awaiting_editor"]} 个 | '
            f'通知主编 {stats["chief_notified"]} 个'
        ))

    # ------------------------------------------------------------------
    # 1. 邀请超时检测
    # ------------------------------------------------------------------
    def _expire_invitations(self, today, stats):
        expired = ReviewAssignment.objects.filter(
            assignment_status='INVITED',
            invitation_expiry__lt=today,
        ).select_related('task', 'reviewer')

        for assignment in expired:
            with transaction.atomic():
                assignment.assignment_status = 'EXPIRED'
                assignment.save(update_fields=['assignment_status'])
            stats['invitations_expired'] += 1
            task = assignment.task
            NotificationService._notify_multiple(
                users=NotificationService._get_editor_users(),
                task=task,
                ntype=Notification.Type.OVERDUE,
                title=f'【邀请过期】任务 {task.task_id} 的审稿邀请已过期',
                content=(
                    f'审稿人 {assignment.reviewer.name}（{assignment.reviewer.email}）'
                    f'未在邀请有效期（{assignment.invitation_expiry}）内响应，'
                    f'邀请已标记为过期。请重新分配审稿人。'
                ),
            )

        # 全部邀请均已过期/拒绝且无一人接受 -> 任务回退 PENDING（ASSIGNED -> PENDING）
        rolled = ReviewTask.objects.filter(status='ASSIGNED').prefetch_related('assignments')
        for task in rolled:
            assignments = list(task.assignments.all())
            if not assignments:
                continue
            alive = [a for a in assignments if a.assignment_status in ('INVITED', 'ACCEPTED')]
            accepted = [a for a in assignments if a.assignment_status == 'ACCEPTED']
            if not alive and not accepted:
                with transaction.atomic():
                    StateMachineService.execute_transition(
                        task, 'PENDING', None, '邀请全部过期/拒绝，系统自动回退待分配'
                    )
                    StateMachineService.increment_retry_count(task)
                stats['tasks_rolled_back'] += 1
                self.stdout.write(f'  任务 {task.task_id} 已回退 PENDING（retry_count +1）')

    # ------------------------------------------------------------------
    # 2. 截止前 7/3/1 天提醒
    # ------------------------------------------------------------------
    def _send_deadline_reminders(self, today, stats):
        active = ReviewAssignment.objects.filter(
            assignment_status__in=['ACCEPTED', 'REVIEWING'],
        ).select_related('task', 'reviewer')

        for assignment in active:
            days_left = (assignment.deadline - today).days
            if days_left not in REMIND_DAYS_BEFORE:
                continue
            task = assignment.task
            title = f'【截止提醒】您的审稿任务将于 {days_left} 天后到期'
            # 当日去重：同任务同审稿人同档位只发一次
            already_sent = Notification.objects.filter(
                user=assignment.reviewer, task=task,
                type=Notification.Type.REMIND, title=title,
                created_at__date=today,
            ).exists()
            if already_sent:
                continue
            NotificationService.send_remind(assignment, days_left)
            stats['reminders_sent'] += 1

    # ------------------------------------------------------------------
    # 3. 审稿超时检测
    # ------------------------------------------------------------------
    def _mark_overdue(self, today, stats):
        overdue = ReviewAssignment.objects.filter(
            assignment_status__in=['ACCEPTED', 'REVIEWING'],
            deadline__lt=today,
        ).select_related('task', 'reviewer')

        for assignment in overdue:
            with transaction.atomic():
                assignment.assignment_status = 'OVERDUE'
                assignment.save(update_fields=['assignment_status'])
            stats['assignments_overdue'] += 1
            NotificationService.send_overdue(assignment)

        # 全部已接受审稿人均到期（SUBMITTED 或 OVERDUE）-> 通知编辑部三选一
        reviewing = ReviewTask.objects.filter(status='REVIEWING').prefetch_related('assignments')
        for task in reviewing:
            assignments = [a for a in task.assignments.all() if a.assignment_status != 'REJECTED']
            accepted = [a for a in assignments if a.assignment_status in
                        ('ACCEPTED', 'REVIEWING', 'SUBMITTED', 'OVERDUE')]
            if not accepted:
                continue
            settled = [a for a in accepted if a.assignment_status in ('SUBMITTED', 'OVERDUE')]
            if len(settled) != len(accepted):
                continue  # 仍有未到期/未提交的审稿人
            title = f'【超时处理】任务 {task.task_id} 审稿人已全部到期，请选择处理方式'
            already_sent = Notification.objects.filter(
                task=task, type=Notification.Type.OVERDUE,
                title=title, created_at__date=today,
            ).exists()
            if already_sent:
                continue
            submitted = sum(1 for a in settled if a.assignment_status == 'SUBMITTED')
            NotificationService._notify_multiple(
                users=NotificationService._get_editor_users(),
                task=task,
                ntype=Notification.Type.OVERDUE,
                title=title,
                content=(
                    f'任务 {task.task_id}《{task.title}》的全部审稿人已到期'
                    f'（已提交 {submitted} 份 / 共 {len(settled)} 位）。\n'
                    f'请通过 POST /api/tasks/{task.task_id}/handle_overdue/ 三选一处理：\n'
                    f'  1. action=summarize —— 基于已提交意见强制汇总\n'
                    f'  2. action=rollback —— 回退待分配（已提交意见保留为历史记录），随后可重新分配\n'
                ),
            )
            stats['tasks_awaiting_editor'] += 1

    # ------------------------------------------------------------------
    # 4. 48小时自动通知主编（S-02：分配困难任务长期无人处理）
    # ------------------------------------------------------------------
    def _notify_editor_in_chief(self, stats):
        now = timezone.now()
        difficult = ReviewTask.objects.filter(
            status='PENDING', retry_count__gt=3,
        )
        for task in difficult:
            recent = Notification.objects.filter(
                task=task,
                type=Notification.Type.REMIND,
                title__startswith=f'【分配困难】任务 {task.task_id}',
                created_at__gte=now - NOTIFY_EDITOR_INTERVAL,
            ).exists()
            if recent:
                continue
            NotificationService.notify_editor_in_chief(
                task=task,
                message=f'该任务已重试 {task.retry_count} 次，超过 48 小时无人处理，系统自动提醒。',
            )
            stats['chief_notified'] += 1
