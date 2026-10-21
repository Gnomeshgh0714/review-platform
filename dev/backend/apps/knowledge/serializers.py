"""
审稿知识库序列化器 - 对应PRD §6.2.7 KnowledgeItem实体序列化

序列化器清单：
- KnowledgeItemSerializer：完整序列化（详情/审核用）
- KnowledgeItemBriefSerializer：检索结果列表用（精简字段）
- AnonymizationReviewSerializer：审核操作入参序列化器
- SearchResultSerializer：检索结果（含冷启动标识）
"""
from rest_framework import serializers

from .models import KnowledgeItem


class KnowledgeItemSerializer(serializers.ModelSerializer):
    """知识库条目完整序列化器 - 详情/审核列表用"""

    anonymization_status_display = serializers.CharField(
        source='get_anonymization_status_display', read_only=True
    )
    reviewed_by_email = serializers.CharField(
        source='reviewed_by.email', read_only=True, default=None
    )
    source_report_id = serializers.CharField(
        source='source_report.report_id', read_only=True, default=None
    )

    class Meta:
        model = KnowledgeItem
        fields = [
            'knowledge_id',
            'source_task_id',
            'source_report_id',
            'subject_area',
            'manuscript_type',
            'keywords',
            'review_year',
            'review_month',
            'review_mode',
            'anonymized_dimensions',
            'anonymized_recommendations',
            'anonymized_summary',
            'template_info',
            'final_decision',
            'tags',
            'anonymization_status',
            'anonymization_status_display',
            'pending_review_segments',
            'reviewed_by',
            'reviewed_by_email',
            'reviewed_at',
            'review_notes',
            'archived_at',
            'created_at',
        ]
        read_only_fields = fields


class KnowledgeItemBriefSerializer(serializers.ModelSerializer):
    """
    知识库条目简要序列化器 - 检索结果列表用

    仅包含列表展示必要字段：
    knowledge_id, subject_area, keywords, tags, final_decision, review_year, review_month
    """

    class Meta:
        model = KnowledgeItem
        fields = [
            'knowledge_id',
            'subject_area',
            'keywords',
            'tags',
            'final_decision',
            'review_year',
            'review_month',
        ]
        read_only_fields = fields


class AnonymizationReviewSerializer(serializers.Serializer):
    """审核匿名化操作序列化器 - POST入参校验"""

    decision = serializers.ChoiceField(
        choices=[
            'APPROVED',              # 通过：不可逆归档
            'REJECTED',              # 退回修改：可修改后重新提交
            'PERMANENTLY_EXCLUDED',  # 永久不归档
        ],
        help_text='审核决策: APPROVED/REJECTED/PERMANENTLY_EXCLUDED',
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text='审核备注（可选）',
    )


class SearchResultSerializer(serializers.Serializer):
    """
    检索结果序列化器 - 含冷启动标识

    结构：
    {
        'count': 总数,
        'page': 当前页,
        'total_pages': 总页数,
        'results': [KnowledgeItemBrief序列化数据],
        'is_cold_start': 是否冷启动降级,
        'cold_start_guide': 冷启动模板评分指引（仅冷启动时返回）,
    }
    """

    count = serializers.IntegerField(help_text='检索结果总数')
    page = serializers.IntegerField(help_text='当前页码')
    total_pages = serializers.IntegerField(help_text='总页数')
    results = KnowledgeItemBriefSerializer(many=True, help_text='检索结果列表')
    is_cold_start = serializers.BooleanField(help_text='是否冷启动降级')
    cold_start_guide = serializers.DictField(
        required=False,
        allow_null=True,
        help_text='冷启动模板评分指引（仅冷启动时返回）',
    )
