"""
通知服务模块 - 对应PRD §3.1.10 notifications

T-02（生产部署批 #023，路线A）：站内信 + 邮件双通道。站内 Notification
为主通道，邮件经 apps/notifications/email.py 同步补发（模板按类型集中
定义）；邮件失败或收件人无邮箱均不阻断站内信。
所有方法均为静态方法，供业务层调用。
"""
import logging

from django.db import transaction

from apps.notifications.email import send_notification_email
from apps.notifications.models import Notification
from apps.users.models import User
from apps.tasks.models import ReviewTask, ReviewAssignment
from apps.forms.models import ReviewOpinion
from apps.summaries.models import SummaryReport

logger = logging.getLogger(__name__)


class NotificationService:
    """通知服务 - 封装各类业务通知的创建逻辑"""

    # ==================== 内部辅助方法 ====================

    @staticmethod
    def _get_editor_users():
        """获取所有编辑部用户（用于通知编辑部）"""
        return User.objects.filter(roles__contains=['EDITOR'], is_active=True)

    @staticmethod
    def _create_notification(user, task, ntype, title, content):
        """
        创建单条通知记录（内部方法）

        :param user: 接收用户
        :param task: 关联任务（可为None）
        :param ntype: Notification.Type 枚举值
        :param title: 通知标题
        :param content: 通知内容
        :return: Notification 实例
        """
        try:
            with transaction.atomic():
                notification = Notification.objects.create(
                    user=user,
                    task=task,
                    type=ntype,
                    title=title,
                    content=content,
                    is_read=False,
                )
        except Exception as e:
            logger.error(
                '创建通知失败: user=%s, type=%s, error=%s',
                getattr(user, 'user_id', None), ntype, str(e),
            )
            raise
        logger.info(
            '通知已创建: user=%s, type=%s, task=%s, title=%s',
            user.user_id, ntype, task.task_id if task else None, title,
        )
        # T-02 邮件通道（#023 路线A）：站内信落库成功后同路径补发邮件——
        # 10 个业务方法（含 _notify_multiple 批量路径）均经此覆盖；
        # 邮件失败或收件人无邮箱只记日志，绝不阻断站内信，容错口径与
        # _notify_multiple 吞单条失败一致；模板见 apps/notifications/email.py
        send_notification_email(user, ntype, {
            'title': title,
            'content': content,
            'task_title': task.title if task else '',
        })
        return notification

    @staticmethod
    def _notify_multiple(users, task, ntype, title, content):
        """批量向多个用户创建相同通知（内部方法）"""
        notifications = []
        for user in users:
            try:
                n = NotificationService._create_notification(user, task, ntype, title, content)
                notifications.append(n)
            except Exception as e:
                logger.error('批量通知创建失败(单条): user=%s, error=%s', user.user_id, str(e))
        return notifications

    # ==================== 业务通知方法 ====================

    @staticmethod
    def send_task_created(task):
        """
        任务创建通知（发给作者：稿件已受理、进入待分配）

        :param task: ReviewTask 审稿任务
        :return: Notification 实例
        """
        author = task.author_user_id
        title = f'【稿件受理】您的稿件《{task.title}》已进入审稿流程'
        content = (
            f'编辑部已受理您的稿件，当前进入待分配阶段。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'稿件类型：{task.manuscript_type}\n'
            f'学科领域：{task.subject_area}\n'
            f'期望完成日期：{task.deadline}\n\n'
            f'编辑部将尽快为您分配审稿人，审稿进度可在"我的稿件"中查看。'
        )
        return NotificationService._create_notification(
            user=author,
            task=task,
            ntype=Notification.Type.TASK_CREATED,
            title=title,
            content=content,
        )

    @staticmethod
    def send_invitation(task, reviewer, assignment=None):
        """
        发送审稿邀请通知（给审稿人）

        :param task: ReviewTask 审稿任务
        :param reviewer: User 审稿人
        :param assignment: ReviewAssignment 分配记录（含截止日期/邀请有效期/说明）
        :return: Notification 实例
        """
        title = f'【审稿邀请】{task.title}'
        content = (
            f'您收到一份新的审稿邀请。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'学科领域：{task.subject_area}\n'
            f'稿件类型：{task.manuscript_type}\n'
            f'期望完成日期：{task.deadline}\n'
            f'审稿模式：{task.get_review_mode_display()}\n'
        )
        if assignment is not None:
            content += (
                f'您的审稿截止日期：{assignment.deadline}\n'
                f'邀请有效期至：{assignment.invitation_expiry}\n'
            )
            if assignment.invitation_note:
                content += f'\n编辑部备注：{assignment.invitation_note}\n'
        content += '\n请在邀请有效期内前往系统接受或拒绝邀请。'
        return NotificationService._create_notification(
            user=reviewer,
            task=task,
            ntype=Notification.Type.INVITATION,
            title=title,
            content=content,
        )

    @staticmethod
    def send_accept(assignment):
        """
        通知编辑部：审稿人接受了邀请

        :param assignment: ReviewAssignment 审稿分配记录
        :return: 创建的通知列表
        """
        task = assignment.task
        reviewer = assignment.reviewer
        title = f'【接受邀请】{reviewer.name} 已接受审稿任务'
        content = (
            f'审稿人 {reviewer.name}（{reviewer.email}）已接受审稿邀请。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'分配编号：{assignment.assignment_id}\n'
            f'截止日期：{assignment.deadline}\n'
            f'接受时间：{assignment.accepted_at}\n\n'
            f'审稿人已进入审稿状态，请关注审稿进度。'
        )
        editors = NotificationService._get_editor_users()
        return NotificationService._notify_multiple(
            users=editors,
            task=task,
            ntype=Notification.Type.ACCEPT,
            title=title,
            content=content,
        )

    @staticmethod
    def send_reject(assignment, reason):
        """
        通知编辑部：审稿人拒绝了邀请

        :param assignment: ReviewAssignment 审稿分配记录
        :param reason: str 拒绝理由
        :return: 创建的通知列表
        """
        task = assignment.task
        reviewer = assignment.reviewer
        title = f'【拒绝邀请】{reviewer.name} 拒绝了审稿任务'
        content = (
            f'审稿人 {reviewer.name}（{reviewer.email}）拒绝了审稿邀请。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'分配编号：{assignment.assignment_id}\n'
            f'拒绝时间：{assignment.rejected_at}\n'
            f'拒绝理由：{reason}\n\n'
            f'请尽快重新分配审稿人。'
        )
        editors = NotificationService._get_editor_users()
        return NotificationService._notify_multiple(
            users=editors,
            task=task,
            ntype=Notification.Type.REJECT,
            title=title,
            content=content,
        )

    @staticmethod
    def send_submit(opinion):
        """
        通知编辑部：审稿人提交了审稿意见

        :param opinion: ReviewOpinion 审稿意见
        :return: 创建的通知列表
        """
        task = opinion.task
        reviewer = opinion.reviewer
        title = f'【意见提交】{reviewer.name} 提交了审稿意见'
        content = (
            f'审稿人 {reviewer.name}（{reviewer.email}）已提交审稿意见。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'意见编号：{opinion.opinion_id}\n'
            f'推荐结论：{opinion.get_recommendation_display()}\n'
            f'提交时间：{opinion.submitted_at}\n\n'
            f'请前往系统查看详细意见，等待全部审稿人提交后可生成汇总报告。'
        )
        editors = NotificationService._get_editor_users()
        return NotificationService._notify_multiple(
            users=editors,
            task=task,
            ntype=Notification.Type.SUBMIT,
            title=title,
            content=content,
        )

    @staticmethod
    def send_summarize(report):
        """
        通知编辑部：汇总报告已生成

        :param report: SummaryReport 汇总报告
        :return: 创建的通知列表
        """
        task = report.task
        title = f'【汇总完成】任务 {task.task_id} 的审稿汇总报告已生成'
        content = (
            f'审稿汇总报告已自动生成。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'报告编号：{report.report_id}\n'
            f'参与汇总意见数：{len(report.opinion_ids)}\n'
            f'生成时间：{report.generated_at}\n\n'
            f'请前往系统查看汇总报告并做出终审决策。'
        )
        editors = NotificationService._get_editor_users()
        return NotificationService._notify_multiple(
            users=editors,
            task=task,
            ntype=Notification.Type.SUMMARIZE,
            title=title,
            content=content,
        )

    @staticmethod
    def send_decide(task, decision):
        """
        通知作者：终审决策已做出

        :param task: ReviewTask 审稿任务
        :param decision: str 终审决策文本
        :return: Notification 实例
        """
        author = task.author_user_id
        title = f'【审稿结果】您的稿件《{task.title}》审稿已完成'
        content = (
            f'您的稿件审稿流程已完成，编辑部已做出终审决策。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'终审决策：{decision}\n'
            f'决策说明：{task.decision_notes or "无"}\n\n'
        )
        if task.publish_opinions_to_author:
            content += '审稿意见已向您公开，请前往系统查看详细意见。\n'
        else:
            content += '审稿意见未向您公开。\n'
        content += '如有疑问，请联系编辑部。'

        return NotificationService._create_notification(
            user=author,
            task=task,
            ntype=Notification.Type.DECIDE,
            title=title,
            content=content,
        )

    @staticmethod
    def send_remind(assignment, days_left):
        """
        发送截止提醒（给审稿人）

        :param assignment: ReviewAssignment 审稿分配记录
        :param days_left: int 剩余天数
        :return: Notification 实例
        """
        task = assignment.task
        reviewer = assignment.reviewer
        title = f'【截止提醒】您的审稿任务将于 {days_left} 天后到期'
        content = (
            f'温馨提醒：您的审稿任务即将到期。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'分配编号：{assignment.assignment_id}\n'
            f'截止日期：{assignment.deadline}\n'
            f'剩余天数：{days_left} 天\n\n'
            f'请尽快完成审稿意见提交，避免超时。'
        )
        return NotificationService._create_notification(
            user=reviewer,
            task=task,
            ntype=Notification.Type.REMIND,
            title=title,
            content=content,
        )

    @staticmethod
    def send_overdue(assignment):
        """
        发送超时通知（给审稿人 + 编辑部）

        :param assignment: ReviewAssignment 审稿分配记录
        :return: 创建的通知列表
        """
        task = assignment.task
        reviewer = assignment.reviewer
        title = f'【超时通知】审稿任务 {task.task_id} 已超时'
        content = (
            f'审稿任务已超时。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'分配编号：{assignment.assignment_id}\n'
            f'审稿人：{reviewer.name}（{reviewer.email}）\n'
            f'截止日期：{assignment.deadline}\n\n'
            f'请尽快处理：审稿人请尽快提交意见，编辑部可考虑重新分配。'
        )
        # 通知审稿人和编辑部
        target_users = list(NotificationService._get_editor_users())
        if reviewer not in target_users:
            target_users.append(reviewer)
        return NotificationService._notify_multiple(
            users=target_users,
            task=task,
            ntype=Notification.Type.OVERDUE,
            title=title,
            content=content,
        )

    @staticmethod
    def notify_editor_in_chief(task, message):
        """
        通知主编（分配困难时调用）

        :param task: ReviewTask 审稿任务
        :param message: str 通知消息内容
        :return: 创建的通知列表
        """
        title = f'【分配困难】任务 {task.task_id} 需要主编介入'
        content = (
            f'审稿人分配遇到困难，需要主编介入处理。\n'
            f'任务编号：{task.task_id}\n'
            f'稿件标题：{task.title}\n'
            f'学科领域：{task.subject_area}\n'
            f'期望审稿人数：{task.expected_reviewer_count}\n'
            f'当前重试次数：{task.retry_count}\n\n'
            f'具体情况：{message}\n\n'
            f'请前往系统手动分配审稿人或调整任务。'
        )
        # 通知所有编辑部用户（含主编，P0不区分主编子角色）
        editors = NotificationService._get_editor_users()
        return NotificationService._notify_multiple(
            users=editors,
            task=task,
            ntype=Notification.Type.REMIND,  # 复用REMIND类型，分配困难提醒
            title=title,
            content=content,
        )
