"""
汇总报告序列化器 - 对应PRD §6.2.6 SummaryReport实体序列化

- SummaryReportSerializer：完整序列化（含全部结构化数据）
- SummaryReportBriefSerializer：简要信息（report_id, task_id, system_recommendation, generated_at）
"""
from rest_framework import serializers
from .models import SummaryReport


class SummaryReportSerializer(serializers.ModelSerializer):
    """汇总报告完整序列化器 - 包含全部结构化数据"""

    task_id = serializers.CharField(source='task.task_id', read_only=True)
    task_title = serializers.CharField(source='task.title', read_only=True)
    task_status = serializers.CharField(source='task.status', read_only=True)

    class Meta:
        model = SummaryReport
        fields = [
            'report_id',
            'task_id',
            'task_title',
            'task_status',
            'opinion_ids',
            'dimension_comparison',
            'recommendation_distribution',
            'conflict_points',
            'consensus_points',
            'revision_suggestions_summary',
            'overall_comments',
            'system_recommendation',
            'editor_decision',
            'round',
            'generated_at',
        ]
        read_only_fields = fields


class SummaryReportBriefSerializer(serializers.ModelSerializer):
    """汇总报告简要序列化器 - 仅含必要信息"""

    task_id = serializers.CharField(source='task.task_id', read_only=True)
    task_title = serializers.CharField(source='task.title', read_only=True)

    class Meta:
        model = SummaryReport
        fields = [
            'report_id',
            'task_id',
            'task_title',
            'system_recommendation',
            'generated_at',
        ]
        read_only_fields = fields
