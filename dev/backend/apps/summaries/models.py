from django.db import IntegrityError, models, transaction
from apps.tasks.models import ReviewTask


class SummaryReport(models.Model):
    """汇总报告 - 对应PRD §6.2.6 SummaryReport实体"""

    report_id = models.CharField(max_length=64, primary_key=True, editable=False)
    task = models.OneToOneField(ReviewTask, on_delete=models.CASCADE, related_name='summary_report', verbose_name='关联任务')
    opinion_ids = models.JSONField('参与汇总意见ID列表', default=list)
    dimension_comparison = models.JSONField('维度对比数据', default=list)
    recommendation_distribution = models.JSONField('推荐意见分布', default=dict)
    conflict_points = models.JSONField('分歧点列表', default=list, blank=True)
    consensus_points = models.JSONField('一致点列表', default=list, blank=True)
    revision_suggestions_summary = models.JSONField('修改建议汇总', default=dict, blank=True)
    overall_comments = models.JSONField('综合评语', default=list)
    system_recommendation = models.JSONField('系统终审建议', default=dict)  # {distribution, matchedRuleId, conclusion}
    editor_decision = models.JSONField('编辑终审决策', default=dict, blank=True)
    round = models.IntegerField('审稿轮次', default=1)  # P1预留，P0=1
    generated_at = models.DateTimeField('生成时间', auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.report_id:
            from django.utils import timezone as tz
            # V1.2 一般#7：当日计数在并发下撞主键会 IntegrityError，改为
            # 保存点+重试（同 forms.ReviewOpinion 模式），重试耗尽后兜底直写
            today = tz.now().strftime('%Y%m%d')
            for _ in range(6):
                count = SummaryReport.objects.filter(report_id__startswith=f'SR-{today}').count()
                self.report_id = f'SR-{today}-{count + 1:04d}'
                try:
                    with transaction.atomic():
                        super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue
            # V1.3 G1：重试耗尽后按最新计数重算一次再直写（原实现带着
            # 已撞号的 ID 直插必再失败）；仍冲突则抛出由调用方处理
            count = SummaryReport.objects.filter(report_id__startswith=f'SR-{today}').count()
            self.report_id = f'SR-{today}-{count + 1:04d}'
            super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
