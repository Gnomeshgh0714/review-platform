"""
审稿表单模块序列化器 - 对应PRD §6.2.4 / §6.2.5

序列化器清单：
- ReviewFormSerializer：序列化审稿表单（含模板快照+维度配置）
- ReviewOpinionSerializer：序列化审稿意见（含维度评分详情）
- ReviewOpinionSubmitSerializer：提交审稿意见（含完整校验逻辑）
- ReviewOpinionDraftSerializer：保存草稿（部分字段可选，自动保存用）
"""
from rest_framework import serializers

from .models import ReviewForm, ReviewOpinion
from .services import FormService


class ReviewFormSerializer(serializers.ModelSerializer):
    """审稿表单序列化器 - 渲染表单时使用"""

    task_title = serializers.CharField(source='task.title', read_only=True)
    task_abstract = serializers.CharField(source='task.abstract', read_only=True)
    task_keywords = serializers.JSONField(source='task.keywords', read_only=True)
    task_subject_area = serializers.CharField(source='task.subject_area', read_only=True)
    task_manuscript_type = serializers.CharField(source='task.manuscript_type', read_only=True)
    task_manuscript_file = serializers.CharField(source='task.manuscript_file', read_only=True)
    task_review_mode = serializers.CharField(source='task.review_mode', read_only=True)
    task_status = serializers.CharField(source='task.status', read_only=True)
    task_deadline = serializers.DateField(source='task.deadline', read_only=True)
    template_name = serializers.CharField(source='template.template_name', read_only=True)

    class Meta:
        model = ReviewForm
        fields = [
            'form_id', 'task', 'task_title', 'task_abstract', 'task_keywords',
            'task_subject_area', 'task_manuscript_type', 'task_manuscript_file',
            'task_review_mode', 'task_status', 'task_deadline',
            'template', 'template_name', 'template_snapshot', 'dimensions',
            'created_at',
        ]
        read_only_fields = [
            'form_id', 'task', 'template', 'template_snapshot',
            'dimensions', 'created_at',
        ]


class ReviewOpinionSerializer(serializers.ModelSerializer):
    """审稿意见序列化器 - 查看意见详情时使用（含维度评分详情）"""

    reviewer_name = serializers.CharField(source='reviewer.name', read_only=True)
    reviewer_email = serializers.CharField(source='reviewer.email', read_only=True)
    task_title = serializers.CharField(source='task.title', read_only=True)
    recommendation_display = serializers.CharField(
        source='get_recommendation_display', read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display', read_only=True
    )
    # 维度评分详情：关联表单维度配置，便于前端渲染
    dimension_scores_detail = serializers.SerializerMethodField()

    class Meta:
        model = ReviewOpinion
        fields = [
            'opinion_id', 'task', 'task_title', 'form', 'assignment',
            'reviewer', 'reviewer_name', 'reviewer_email',
            'dimension_scores', 'dimension_scores_detail',
            'recommendation', 'recommendation_display',
            'overall_comment', 'revision_suggestions',
            'status', 'status_display', 'round',
            'submitted_at', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'opinion_id', 'task', 'form', 'assignment', 'reviewer',
            'status', 'submitted_at', 'created_at', 'updated_at',
        ]

    def get_dimension_scores_detail(self, obj):
        """获取维度评分详情：将评分数据与表单维度配置关联"""
        try:
            form = obj.form
            dim_config_map = {}
            for dim in (form.dimensions or []):
                dim_id = dim.get('dimensionId') or dim.get('dimension_id')
                dim_config_map[dim_id] = dim

            result = []
            for score_item in (obj.dimension_scores or []):
                dim_id = score_item.get('dimensionId') or score_item.get('dimension_id')
                dim_cfg = dim_config_map.get(dim_id, {})
                result.append({
                    'dimensionId': dim_id,
                    'dimensionName': dim_cfg.get('dimensionName', ''),
                    'description': dim_cfg.get('description', ''),
                    'minWords': dim_cfg.get('minWords', 50),
                    'score': score_item.get('score'),
                    'comment': score_item.get('comment', ''),
                })
            return result
        except Exception:
            return obj.dimension_scores or []


class ReviewOpinionSubmitSerializer(serializers.Serializer):
    """
    提交审稿意见序列化器 - 含完整校验逻辑

    校验规则（对应PRD §6.3.3）：
    1. 维度完整性：必须覆盖表单全部维度
    2. 评分范围：每维度1-5分
    3. 文字说明：每维度≥50字（模板可覆盖minWords）
    4. 综合评语：≥100字
    5. 总体推荐：必须为有效枚举值
    """

    dimension_scores = serializers.ListField(
        child=serializers.DictField(),
        help_text='维度评分列表 [{dimensionId, score, comment}]',
    )
    recommendation = serializers.ChoiceField(
        choices=ReviewOpinion.Recommendation.choices,
        help_text='总体推荐: ACCEPT/MINOR_REVISION/MAJOR_REVISION/REJECT',
    )
    overall_comment = serializers.CharField(
        help_text='综合评语（≥100字）',
    )
    revision_suggestions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text='修改建议列表（可选）',
    )

    def __init__(self, *args, **kwargs):
        # 允许传入form实例用于校验
        self.form = kwargs.pop('form', None)
        super().__init__(*args, **kwargs)

    def validate(self, attrs):
        """整体校验 - 委托给FormService.validate_opinion"""
        if not self.form:
            raise serializers.ValidationError('缺少表单实例，无法校验')

        try:
            validated = FormService.validate_opinion(attrs, self.form)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

        return validated


class ReviewOpinionDraftSerializer(serializers.Serializer):
    """
    保存草稿序列化器 - 自动保存用，部分字段可选

    草稿不校验完整性、字数下限，仅校验数据类型和评分范围。
    前端每60秒自动调用保存草稿接口。
    """

    dimension_scores = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text='维度评分列表（草稿可部分填写）',
    )
    recommendation = serializers.ChoiceField(
        choices=ReviewOpinion.Recommendation.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='总体推荐（草稿可选）',
    )
    overall_comment = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text='综合评语（草稿可部分填写）',
    )
    revision_suggestions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text='修改建议列表（可选）',
    )

    def validate_dimension_scores(self, value):
        """草稿仅校验评分范围，不校验维度完整性和字数"""
        if not value:
            return value

        for item in value:
            score = item.get('score')
            if score is not None:
                try:
                    score_int = int(score)
                    if not (1 <= score_int <= 5):
                        raise serializers.ValidationError(
                            f'维度评分({score_int})不在1-5范围内'
                        )
                except (ValueError, TypeError):
                    raise serializers.ValidationError(
                        f'维度评分({score})不是有效整数'
                    )
        return value
