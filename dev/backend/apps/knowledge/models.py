from django.db import IntegrityError, models, transaction
from apps.users.models import User
from apps.summaries.models import SummaryReport


class KnowledgeItem(models.Model):
    """知识库条目 - 对应PRD §6.2.7 KnowledgeItem实体"""

    class AnonymizationStatus(models.TextChoices):
        PENDING_REVIEW = 'PENDING_REVIEW', '待审核'
        APPROVED = 'APPROVED', '已通过'
        REJECTED = 'REJECTED', '已退回'
        PERMANENTLY_EXCLUDED = 'PERMANENTLY_EXCLUDED', '永久不归档'

    knowledge_id = models.CharField(max_length=64, primary_key=True, editable=False)
    source_task_id = models.CharField('来源任务ID', max_length=64)  # 仅编辑可见
    source_report = models.ForeignKey(SummaryReport, on_delete=models.SET_NULL, null=True, verbose_name='来源汇总报告')
    subject_area = models.CharField('学科领域', max_length=50)
    manuscript_type = models.CharField('稿件类型', max_length=50)
    keywords = models.JSONField('关键词', default=list)
    review_year = models.IntegerField('审稿年份')
    review_month = models.IntegerField('审稿月份')
    review_mode = models.CharField('审稿模式', max_length=20)
    anonymized_dimensions = models.JSONField('匿名化维度数据', default=list)
    anonymized_recommendations = models.JSONField('匿名化推荐分布', default=dict)
    anonymized_summary = models.TextField('匿名化汇总报告')
    template_info = models.JSONField('模板信息', default=dict)
    final_decision = models.CharField('终审决策', max_length=30)
    tags = models.JSONField('自动标签', default=list)
    anonymization_status = models.CharField(
        '匿名化状态', max_length=30, choices=AnonymizationStatus.choices,
        default=AnonymizationStatus.PENDING_REVIEW
    )
    pending_review_segments = models.JSONField('待审核文字段', default=list, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_knowledge_items', verbose_name='审核人'
    )
    reviewed_at = models.DateTimeField('审核时间', null=True, blank=True)
    # 评审意见 V1.2 严重#5：人工审核备注此前只作为入参传递、从未落库，
    # 审核 API 的 notes 参数形同虚设
    review_notes = models.TextField('人工审核备注', blank=True, default='')
    archived_at = models.DateTimeField('归档时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['anonymization_status']),
            models.Index(fields=['subject_area']),
            models.Index(fields=['final_decision']),
        ]

    def save(self, *args, **kwargs):
        if not self.knowledge_id:
            from django.utils import timezone as tz
            # V1.2 一般#7：当日计数在并发下撞主键会 IntegrityError，改为
            # 保存点+重试（同 forms.ReviewOpinion 模式），重试耗尽后兜底直写
            today = tz.now().strftime('%Y%m%d')
            for _ in range(6):
                count = KnowledgeItem.objects.filter(knowledge_id__startswith=f'KI-{today}').count()
                self.knowledge_id = f'KI-{today}-{count + 1:04d}'
                try:
                    with transaction.atomic():
                        super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue
            # V1.3 G1：重试耗尽后按最新计数重算一次再直写（原实现带着
            # 已撞号的 ID 直插必再失败）；仍冲突则抛出由调用方处理
            count = KnowledgeItem.objects.filter(knowledge_id__startswith=f'KI-{today}').count()
            self.knowledge_id = f'KI-{today}-{count + 1:04d}'
            super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class AccessLog(models.Model):
    """访问日志 - 对应PRD §3.1.11 access_logs"""

    log_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='操作人')
    action = models.CharField('操作类型', max_length=50)  # SEARCH_KB, VIEW_KB_ITEM等
    target_id = models.CharField('操作目标ID', max_length=64, blank=True)
    ip_address = models.GenericIPAddressField('IP地址', null=True, blank=True)
    created_at = models.DateTimeField('记录时间', auto_now_add=True)
