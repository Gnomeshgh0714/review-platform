from django.db import models
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
            today = tz.now().strftime('%Y%m%d')
            count = SummaryReport.objects.filter(report_id__startswith=f'SR-{today}').count()
            self.report_id = f'SR-{today}-{count + 1:04d}'
        super().save(*args, **kwargs)
