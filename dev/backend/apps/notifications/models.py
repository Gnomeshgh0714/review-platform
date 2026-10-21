from django.db import models
from apps.users.models import User
from apps.tasks.models import ReviewTask


class Notification(models.Model):
    """通知 - 对应PRD §3.1.10 notifications"""

    class Type(models.TextChoices):
        TASK_CREATED = 'TASK_CREATED', '任务创建'
        INVITATION = 'INVITATION', '审稿邀请'
        ACCEPT = 'ACCEPT', '接受邀请'
        REJECT = 'REJECT', '拒绝邀请'
        SUBMIT = 'SUBMIT', '意见提交'
        SUMMARIZE = 'SUMMARIZE', '汇总完成'
        DECIDE = 'DECIDE', '决策完成'
        REMIND = 'REMIND', '截止提醒'
        OVERDUE = 'OVERDUE', '超时通知'

    notification_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name='接收人')
    task = models.ForeignKey(ReviewTask, on_delete=models.CASCADE, null=True, blank=True, verbose_name='关联任务')
    type = models.CharField('通知类型', max_length=50, choices=Type.choices)
    title = models.CharField('通知标题', max_length=200)
    content = models.TextField('通知内容')
    is_read = models.BooleanField('是否已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['task']),
        ]
