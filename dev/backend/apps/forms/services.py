"""
审稿表单服务模块 - 对应PRD §6.2.4 / §6.2.5

职责：
1. 任务创建时自动创建审稿表单（冻结模板快照）
2. 校验审稿意见（维度完整性、评分范围、字数下限）
3. 匿名化审稿意见（双盲保护：作者查看时移除审稿人身份）
"""
import copy
import logging

from django.db import transaction
from django.utils import timezone

from apps.tasks.models import ReviewTask, Template
from apps.forms.models import ReviewForm, ReviewOpinion

logger = logging.getLogger(__name__)


class FormService:
    """审稿表单服务 - 封装表单创建、意见校验、匿名化等业务逻辑"""

    # ==================== 表单创建 ====================

    @staticmethod
    def create_form_for_task(task: ReviewTask) -> ReviewForm:
        """
        任务创建时自动创建审稿表单（加载模板快照，冻结）

        :param task: ReviewTask 审稿任务
        :return: ReviewForm 审稿表单实例
        :raises Template.DoesNotExist: 模板不存在
        """
        # 已存在表单则直接返回（幂等）
        existing = ReviewForm.objects.filter(task=task).first()
        if existing:
            logger.info('审稿表单已存在，跳过创建: task=%s, form=%s', task.task_id, existing.form_id)
            return existing

        # 加载模板
        template = Template.objects.get(template_id=task.template_id)

        # 冻结模板快照：拷贝模板维度配置，后续模板变更不影响已创建的表单
        template_snapshot = {
            'template_id': template.template_id,
            'template_name': template.template_name,
            'template_type': template.template_type,
            'subject_area': template.subject_area,
            'dimensions': copy.deepcopy(template.dimensions or []),
        }

        # 维度配置冗余存于表单，便于渲染时直接使用
        dimensions = copy.deepcopy(template.dimensions or [])

        form = ReviewForm.objects.create(
            task=task,
            template=template,
            template_snapshot=template_snapshot,
            dimensions=dimensions,
        )

        logger.info(
            '审稿表单已创建: task=%s, form=%s, template=%s, 维度数=%d',
            task.task_id, form.form_id, template.template_id, len(dimensions),
        )
        return form

    # ==================== 审稿意见校验 ====================

    @staticmethod
    def validate_opinion(opinion_data: dict, form: ReviewForm) -> dict:
        """
        校验审稿意见（提交时调用，草稿不校验）

        校验规则（对应PRD §6.2.5 + §6.3.3）：
        1. 维度完整性：必须覆盖表单全部维度
        2. 评分范围：每维度评分1-5分
        3. 文字说明：每维度字数≥50字（模板可覆盖 minWords）
        4. 综合评语：≥100字

        :param opinion_data: dict 审稿意见数据
            {
                dimension_scores: [{dimensionId, score, comment}, ...],
                recommendation: 'ACCEPT'/'MINOR_REVISION'/'MAJOR_REVISION'/'REJECT',
                overall_comment: str,
                revision_suggestions: [str, ...]  # 可选
            }
        :param form: ReviewForm 关联表单
        :return: dict 清洗后的有效数据
        :raises ValueError: 校验失败时抛出，message为错误描述
        """
        errors = []

        # ---------- 1. 维度评分校验 ----------
        dimension_scores = opinion_data.get('dimension_scores') or []
        form_dimensions = form.dimensions or []

        # 维度数量必须在2-8之间（PRD §6.2.4）
        if not (2 <= len(form_dimensions) <= 8):
            errors.append(f'表单维度数量({len(form_dimensions)})不在2-8范围内')

        # 构建维度ID -> 维度配置 的映射
        dim_config_map = {}
        for dim in form_dimensions:
            dim_id = dim.get('dimensionId') or dim.get('dimension_id')
            dim_config_map[dim_id] = dim

        # 构建提交的维度评分映射
        submitted_scores = {}
        for item in dimension_scores:
            dim_id = item.get('dimensionId') or item.get('dimension_id')
            submitted_scores[dim_id] = item

        # 检查维度完整性：每个表单维度都必须有对应评分
        missing_dims = []
        for dim_id, dim_cfg in dim_config_map.items():
            if dim_id not in submitted_scores:
                missing_dims.append(dim_id)
                continue

            item = submitted_scores[dim_id]
            score = item.get('score')
            comment = item.get('comment', '') or ''

            # 评分范围校验：1-5
            if score is None:
                errors.append(f'维度[{dim_id}]缺少评分')
            else:
                try:
                    score_int = int(score)
                    if not (1 <= score_int <= 5):
                        errors.append(f'维度[{dim_id}]评分({score_int})不在1-5范围内')
                except (ValueError, TypeError):
                    errors.append(f'维度[{dim_id}]评分({score})不是有效整数')

            # 文字说明字数校验
            min_words = dim_cfg.get('minWords', 50)
            # 去除空白字符后计算字数（中文按字符计）
            comment_cleaned = comment.strip()
            if len(comment_cleaned) < min_words:
                errors.append(
                    f'维度[{dim_id}]文字说明不足{min_words}字（当前{len(comment_cleaned)}字）'
                )

        if missing_dims:
            errors.append(f'缺少维度评分: {", ".join(missing_dims)}')

        # 检查是否有多余维度的评分
        extra_dims = set(submitted_scores.keys()) - set(dim_config_map.keys())
        if extra_dims:
            errors.append(f'存在表单未定义的维度评分: {", ".join(extra_dims)}')

        # ---------- 2. 总体推荐校验 ----------
        recommendation = opinion_data.get('recommendation', '')
        valid_recommendations = [c[0] for c in ReviewOpinion.Recommendation.choices]
        if recommendation not in valid_recommendations:
            errors.append(
                f'总体推荐值({recommendation})无效，有效值: {", ".join(valid_recommendations)}'
            )

        # ---------- 3. 综合评语字数校验 ----------
        overall_comment = (opinion_data.get('overall_comment') or '').strip()
        if len(overall_comment) < 100:
            errors.append(
                f'综合评语不足100字（当前{len(overall_comment)}字）'
            )

        if errors:
            raise ValueError('；'.join(errors))

        # 返回清洗后的数据
        return {
            'dimension_scores': dimension_scores,
            'recommendation': recommendation,
            'overall_comment': overall_comment,
            'revision_suggestions': opinion_data.get('revision_suggestions') or [],
        }

    # ==================== 审稿意见匿名化 ====================

    @staticmethod
    def anonymize_opinion(opinion: ReviewOpinion) -> dict:
        """
        匿名化审稿意见（双盲保护：作者查看时移除审稿人身份信息）

        移除字段：
        - reviewer（审稿人ID）
        - reviewer_name（审稿人姓名）
        - reviewer_email（审稿人邮箱）
        - assignment（分配记录ID）

        保留字段：意见内容、维度评分、推荐结论等

        :param opinion: ReviewOpinion 审稿意见实例
        :return: dict 匿名化后的意见字典
        """
        return {
            'opinion_id': opinion.opinion_id,
            'task': opinion.task_id,
            'form': opinion.form_id,
            # 审稿人身份信息已移除（双盲保护）
            # 'reviewer': opinion.reviewer_id,
            # 'assignment': opinion.assignment_id,
            'dimension_scores': opinion.dimension_scores or [],
            'recommendation': opinion.recommendation,
            'recommendation_display': opinion.get_recommendation_display(),
            'overall_comment': opinion.overall_comment,
            'revision_suggestions': opinion.revision_suggestions or [],
            'status': opinion.status,
            'round': opinion.round,
            'submitted_at': opinion.submitted_at,
            'created_at': opinion.created_at,
            'updated_at': opinion.updated_at,
            # 匿名标识，前端可据此隐藏审稿人信息
            'is_anonymized': True,
        }
