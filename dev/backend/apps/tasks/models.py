from django.db import models
from apps.users.models import User


class ReviewTask(models.Model):
    """审稿任务 - 对应PRD §6.2.2 ReviewTask实体"""

    class Status(models.TextChoices):
        PENDING = 'PENDING', '待分配'
        ASSIGNED = 'ASSIGNED', '已分配'
        REVIEWING = 'REVIEWING', '审稿中'
        SUBMITTED = 'SUBMITTED', '已提交'
        SUMMARIZED = 'SUMMARIZED', '已汇总'
        DECIDED = 'DECIDED', '已决策'

    class ReviewMode(models.TextChoices):
        SINGLE_BLIND = 'SINGLE_BLIND', '单盲'
        DOUBLE_BLIND = 'DOUBLE_BLIND', '双盲'

    task_id = models.CharField(max_length=64, primary_key=True, editable=False)
    title = models.CharField('稿件标题', max_length=200)
    abstract = models.TextField('稿件摘要', max_length=2000)
    keywords = models.JSONField('关键词', default=list)
    subject_area = models.CharField('学科领域', max_length=50)
    manuscript_type = models.CharField('稿件类型', max_length=50)
    manuscript_file = models.CharField('稿件PDF路径', max_length=500)
    review_mode = models.CharField('审稿模式', max_length=20, choices=ReviewMode.choices)
    expected_reviewer_count = models.IntegerField('期望审稿人数', default=3)
    deadline = models.DateField('期望完成日期')
    additional_notes = models.TextField('附加说明', max_length=1000, blank=True)
    template_id = models.CharField('关联模板ID', max_length=64)
    author_user_id = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='authored_tasks',
        verbose_name='作者'
    )
    status = models.CharField(
        '任务状态', max_length=20, choices=Status.choices, default=Status.PENDING
    )
    final_decision = models.CharField('终审决策', max_length=30, blank=True)
    decision_notes = models.TextField('决策说明', blank=True)
    publish_opinions_to_author = models.BooleanField('向作者发布意见', default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='created_tasks',
        verbose_name='创建人'
    )
    retry_count = models.IntegerField('任务级重试次数', default=0)  # N-02新增
    version = models.IntegerField('乐观锁版本号', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    def save(self, *args, **kwargs):
        if not self.task_id:
            from django.utils import timezone as tz
            today = tz.now().strftime('%Y%m%d')
            count = ReviewTask.objects.filter(
                task_id__startswith=f'RT-{today}'
            ).count()
            self.task_id = f'RT-{today}-{count + 1:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.task_id} - {self.title[:30]}'


class ReviewAssignment(models.Model):
    """审稿分配记录 - 对应PRD §6.2.3 ReviewAssignment实体（原Reviewer）"""

    class AssignmentStatus(models.TextChoices):
        INVITED = 'INVITED', '已邀请'
        ACCEPTED = 'ACCEPTED', '已接受'
        REJECTED = 'REJECTED', '已拒绝'
        REVIEWING = 'REVIEWING', '审稿中'
        SUBMITTED = 'SUBMITTED', '已提交'
        OVERDUE = 'OVERDUE', '已超时'
        EXPIRED = 'EXPIRED', '邀请过期'

    assignment_id = models.CharField(max_length=64, primary_key=True, editable=False)
    task = models.ForeignKey(
        ReviewTask, on_delete=models.CASCADE, related_name='assignments',
        verbose_name='关联任务'
    )
    reviewer = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='review_assignments',
        verbose_name='审稿人'
    )
    deadline = models.DateField('截止日期')
    invitation_note = models.TextField('邀请说明', blank=True)
    invitation_expiry = models.DateField('邀请有效期')
    assignment_status = models.CharField(
        '分配状态', max_length=30, choices=AssignmentStatus.choices,
        default=AssignmentStatus.INVITED
    )
    attempt_count = models.IntegerField('审稿人级分配次数', default=1)  # N-02澄清语义
    accepted_at = models.DateTimeField('接受时间', null=True, blank=True)
    rejected_at = models.DateTimeField('拒绝时间', null=True, blank=True)
    rejected_reason = models.TextField('拒绝理由', blank=True)
    submitted_at = models.DateTimeField('提交时间', null=True, blank=True)
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='assigned_reviews',
        verbose_name='分配人'
    )
    assigned_at = models.DateTimeField('分配时间', auto_now_add=True)

    class Meta:
        unique_together = [('task', 'reviewer')]  # 防止重复分配
        indexes = [
            models.Index(fields=['task', 'assignment_status']),
            models.Index(fields=['reviewer', 'assignment_status']),
            models.Index(fields=['deadline']),
        ]

    def save(self, *args, **kwargs):
        if not self.assignment_id:
            from django.utils import timezone as tz
            today = tz.now().strftime('%Y%m%d')
            count = ReviewAssignment.objects.filter(
                assignment_id__startswith=f'RA-{today}'
            ).count()
            self.assignment_id = f'RA-{today}-{count + 1:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.assignment_id} - {self.task.task_id} - {self.reviewer.name}'


class StateLog(models.Model):
    """状态变更日志 - 对应PRD §3.1.9 state_logs"""

    class OperatorType(models.TextChoices):
        SYSTEM = 'SYSTEM', '系统'
        EDITOR = 'EDITOR', '编辑部'

    log_id = models.BigAutoField(primary_key=True)
    task = models.ForeignKey(
        ReviewTask, on_delete=models.CASCADE, related_name='state_logs',
        verbose_name='关联任务'
    )
    from_state = models.CharField('变更前状态', max_length=20, blank=True)
    to_state = models.CharField('变更后状态', max_length=20)
    operator_type = models.CharField('操作者类型', max_length=20, choices=OperatorType.choices)
    operator_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='操作人'
    )
    trigger_reason = models.TextField('触发原因', blank=True)
    created_at = models.DateTimeField('记录时间', auto_now_add=True)

    def __str__(self):
        return f'{self.task.task_id}: {self.from_state} -> {self.to_state}'


class Template(models.Model):
    """审稿模板 - 对应PRD §6.2.8 Template实体"""

    class TemplateType(models.TextChoices):
        SYSTEM_DEFAULT = 'SYSTEM_DEFAULT', '系统预设'
        CUSTOM = 'CUSTOM', '自定义'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', '启用'
        INACTIVE = 'INACTIVE', '停用'

    template_id = models.CharField(max_length=64, primary_key=True, editable=False)
    template_name = models.CharField('模板名称', max_length=100)
    template_type = models.CharField('模板类型', max_length=20, choices=TemplateType.choices, default=TemplateType.CUSTOM)
    subject_area = models.CharField('适用学科', max_length=50, blank=True)
    dimensions = models.JSONField('维度配置', default=list)  # [{dimensionId, dimensionName, description, minWords}]
    status = models.CharField('状态', max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='created_templates',
        verbose_name='创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    def save(self, *args, **kwargs):
        if not self.template_id:
            from django.utils import timezone as tz
            today = tz.now().strftime('%Y%m%d')
            count = Template.objects.filter(
                template_id__startswith=f'TPL-{today}'
            ).count()
            self.template_id = f'TPL-{today}-{count + 1:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.template_id} - {self.template_name}'
