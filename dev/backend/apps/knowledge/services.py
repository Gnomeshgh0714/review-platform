"""
审稿知识库服务层 - 对应PRD §3.1.12 审稿知识库功能

服务类：
- AnonymizationService: 第一阶段自动匿名化
- KnowledgeService: 第二阶段人工审核、检索、详情、导出
"""
import re
import logging
from datetime import timedelta
from django.utils import timezone as tz
from django.db.models import Q

from .models import KnowledgeItem, AccessLog

logger = logging.getLogger(__name__)


class AnonymizationService:
    """第一阶段自动匿名化服务"""

    # 4类检测正则规则
    DETECTION_RULES = {
        'pronoun': {
            'label': '指代词检测',
            'patterns': [
                r'贵校', r'您团队', r'贵单位', r'贵所',
                r'张教授', r'李教授', r'王教授', r'刘教授',
                r'教授\s*先生', r'博士\s*先生',
                r'该校', r'该团队', r'该研究所', r'该实验室',
            ],
        },
        'self_citation': {
            'label': '自引检测',
            'patterns': [
                r"author's previous work",
                r"the author's earlier",
                r"作者\s*先前\s*的\s*研究",
                r"作者\s*之前\s*的\s*工作",
                r"如前所述.*作者",
                r"author et al\.",
            ],
        },
        'institution': {
            'label': '机构名检测',
            'patterns': [
                r'北京大学', r'清华大学', r'复旦大学', r'上海交通大学',
                r'浙江大学', r'南京大学', r'中山大学', r'中国人民大学',
                r'中国科学院', r'中国社会科学院',
                r'Harvard', r'MIT', r'Stanford', r'Oxford', r'Cambridge',
            ],
        },
        'grant_number': {
            'label': '基金编号检测',
            'patterns': [
                r'(?:国家自然科学基金|NSFC)\s*[A-Z]?\d{8}',
                r'(?:国家社科基金|NSSFC)\s*[A-Z]?\d{8}',
                r'(?:教育部|MOE)\s*[A-Z]?\d{6,}',
                r'Grant\s*(?:No\.?|Number)\s*\d{6,}',
                r'Project\s*\d{6,}',
            ],
        },
    }

    @classmethod
    def auto_anonymize(cls, task, report=None):
        """
        第一阶段自动匿名化

        :param task: ReviewTask 实例
        :param report: SummaryReport 实例（可选，为None时仅归档意见数据）
        :return: KnowledgeItem 实例
        :raises ValueError: 去重检查失败时
        """
        # 去重检查
        existing = KnowledgeItem.objects.filter(source_task_id=task.task_id).first()
        if existing:
            raise ValueError(f'任务 {task.task_id} 已有归档记录 {existing.knowledge_id}')

        # 构建匿名化数据
        anonymized_dims = cls._build_anonymized_dimensions(task, report)
        anonymized_recs = cls._build_anonymized_recommendations(report)
        anonymized_summary = cls._build_anonymized_summary(task, report)
        pending_segments = cls._scan_segments(anonymized_summary)
        tags = cls._generate_tags(task, report)
        keywords = cls._extract_keywords(task)

        # 模板信息（脱敏）
        template_info = {
            'dimensions': anonymized_dims if isinstance(anonymized_dims, list) else [],
            'source_template_id': getattr(task, 'template_id', ''),
        }

        # 终审决策
        final_decision = task.final_decision or ''

        now = tz.now()

        item = KnowledgeItem.objects.create(
            source_task_id=task.task_id,
            source_report=report,
            subject_area=task.subject_area,
            manuscript_type=task.manuscript_type,
            keywords=keywords,
            review_year=now.year,
            review_month=now.month,
            review_mode=task.review_mode,
            anonymized_dimensions=anonymized_dims if isinstance(anonymized_dims, list) else [],
            anonymized_recommendations=anonymized_recs,
            anonymized_summary=anonymized_summary,
            template_info=template_info,
            final_decision=final_decision,
            tags=tags,
            anonymization_status=KnowledgeItem.AnonymizationStatus.PENDING_REVIEW,
            pending_review_segments=pending_segments,
        )

        logger.info(f'知识库归档: task={task.task_id}, ki={item.knowledge_id}, pending_segs={len(pending_segments)}')
        return item

    # 审稿人身份键（汇总报告实际使用 camelCase，兼容历史 underscore 写法）
    IDENTITY_KEYS = (
        'reviewerId', 'reviewerName', 'reviewerEmail',
        'reviewer_id', 'reviewer_name', 'reviewer_email',
    )

    @classmethod
    def _strip_identity_keys(cls, value):
        """递归移除任意嵌套层级中的审稿人身份键（对应评审意见 V1.1 致命#8）

        汇总报告的 dimension_comparison.scores / overall_comments /
        revision_suggestions 均以 camelCase 键携带 reviewerId/reviewerName，
        原 top-level underscore 过滤对这些结构是空操作。
        """
        if isinstance(value, dict):
            return {
                k: cls._strip_identity_keys(v)
                for k, v in value.items()
                if k not in cls.IDENTITY_KEYS
            }
        if isinstance(value, list):
            return [cls._strip_identity_keys(v) for v in value]
        return value

    @classmethod
    def _build_anonymized_dimensions(cls, task, report):
        """构建匿名化维度数据 - 移除审稿人身份"""
        if report and report.dimension_comparison:
            # 递归脱敏：scores 内的 reviewerId/reviewerName 一并移除，
            # 保留 opinionId/score/comment（位置序即"审稿人A/B"口径）
            return cls._strip_identity_keys(report.dimension_comparison)
        return []

    @classmethod
    def _build_anonymized_recommendations(cls, report):
        """构建匿名化推荐分布"""
        if report and report.recommendation_distribution:
            return dict(report.recommendation_distribution)
        return {}

    @classmethod
    def _build_anonymized_summary(cls, task, report):
        """构建匿名化汇总文本 - 替换身份信息"""
        parts = []

        # 稿件信息（标题替换为学科+关键词）
        keywords_str = ', '.join(task.keywords) if task.keywords else '无'
        parts.append(f'【稿件信息】学科: {task.subject_area}, 类型: {task.manuscript_type}, 关键词: {keywords_str}')

        # 审稿模式
        parts.append(f'【审稿模式】{task.get_review_mode_display()}')

        # 汇总报告数据
        if report:
            # 推荐分布
            if report.recommendation_distribution:
                dist_str = ', '.join(f'{k}: {v}' for k, v in report.recommendation_distribution.items())
                parts.append(f'【推荐分布】{dist_str}')

            # 维度对比（键名对齐汇总报告结构：dimensionName/dimensionId/scores[].score）
            if report.dimension_comparison:
                parts.append('【维度评分对比】')
                for dim in report.dimension_comparison:
                    if isinstance(dim, dict):
                        dim_name = dim.get(
                            'dimensionName',
                            dim.get('dimensionId', dim.get('dimension', '未知维度')),
                        )
                        scores_raw = [
                            s.get('score')
                            for s in dim.get('scores', [])
                            if isinstance(s, dict) and s.get('score') is not None
                        ]
                        # 只渲染分值数字，不落原始 dict（scores 携带审稿人身份键）
                        avg = (
                            round(sum(scores_raw) / len(scores_raw), 2)
                            if scores_raw else '无'
                        )
                        parts.append(f'  {dim_name}: 评分={scores_raw}, 均值={avg}')

            # 分歧点（detect_conflicts 输出键：dimensionName/dimensionId/distributionText）
            if report.conflict_points:
                parts.append('【分歧点】')
                for cp in report.conflict_points:
                    if isinstance(cp, dict):
                        dim_name = cp.get('dimensionName', cp.get('dimensionId', ''))
                        desc = cp.get('distributionText', cp.get('description', ''))
                        parts.append(f'  {dim_name}: {desc}')

            # 一致点（analyze_consensus 输出键：dimensionName/dimensionId/description）
            if report.consensus_points:
                parts.append('【一致点】')
                for cp in report.consensus_points:
                    if isinstance(cp, dict):
                        dim_name = cp.get('dimensionName', cp.get('dimensionId', ''))
                        parts.append(f'  {dim_name}: {cp.get("description", "")}')

            # 综合评语（匿名化：移除审稿人身份）
            if report.overall_comments:
                parts.append('【综合评语】')
                for i, comment in enumerate(report.overall_comments):
                    if isinstance(comment, dict):
                        # 移除审稿人身份字段
                        text = comment.get('comment', comment.get('text', ''))
                        parts.append(f'  审稿人{chr(65 + i)}: {text}')
                    elif isinstance(comment, str):
                        parts.append(f'  审稿人{chr(65 + i)}: {comment}')

            # 系统建议
            if report.system_recommendation:
                sr = report.system_recommendation
                if isinstance(sr, dict):
                    parts.append(f'【系统建议】规则: {sr.get("matchedRuleId", "未匹配")}, 结论: {sr.get("conclusion", "")}')

        # 终审决策
        if task.final_decision:
            parts.append(f'【终审决策】{task.final_decision}')

        return '\n'.join(parts)

    @classmethod
    def _scan_segments(cls, text):
        """
        扫描文本中的4类检测规则，返回待审核段

        :return: list of {type, label, matched, context}
        """
        if not text:
            return []

        segments = []
        lines = text.split('\n')

        for line_idx, line in enumerate(lines, 1):
            for rule_type, rule_info in cls.DETECTION_RULES.items():
                for pattern in rule_info['patterns']:
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        start = max(0, match.start() - 20)
                        end = min(len(line), match.end() + 20)
                        context = line[start:end]
                        segments.append({
                            'type': rule_type,
                            'label': rule_info['label'],
                            'matched': match.group(),
                            'context': context,
                            'line': line_idx,
                        })

        return segments

    @classmethod
    def _generate_tags(cls, task, report):
        """自动生成标签"""
        tags = []

        # 学科标签
        if task.subject_area:
            tags.append(task.subject_area)

        # 类型标签
        if task.manuscript_type:
            tags.append(task.manuscript_type)

        # 终审决策标签
        if task.final_decision:
            tags.append(task.final_decision)

        # 推荐意见标签
        if report and report.recommendation_distribution:
            for rec, count in report.recommendation_distribution.items():
                if count > 0:
                    tags.append(rec)

        # 评分区间标签（键名对齐：均值需从 scores[].score 现算，报告无 avg 键）
        if report and report.dimension_comparison:
            for dim in report.dimension_comparison:
                if isinstance(dim, dict):
                    scores_raw = [
                        s.get('score')
                        for s in dim.get('scores', [])
                        if isinstance(s, dict) and s.get('score') is not None
                    ]
                    avg = sum(scores_raw) / len(scores_raw) if scores_raw else 0
                    if avg >= 4:
                        tags.append('high_score')
                    elif avg >= 3:
                        tags.append('mid_score')
                    else:
                        tags.append('low_score')

        return list(set(tags))

    @classmethod
    def _extract_keywords(cls, task):
        """提取关键词（从任务关键词字段）"""
        if task.keywords:
            return task.keywords
        return []


class KnowledgeService:
    """知识库服务 - 人工审核、检索、详情、导出"""

    # 冷启动模板评分指引
    COLD_START_GUIDE = {
        'title': '审稿评分指引（冷启动）',
        'description': '当前知识库数据较少，以下为标准四维模板评分指引供参考',
        'dimensions': [
            {
                'name': '研究意义',
                'code': 'SIGNIFICANCE',
                'guidelines': {
                    5: '具有重大理论或实践意义，开创性贡献',
                    4: '有显著意义，对领域有重要贡献',
                    3: '有一定意义，但贡献有限',
                    2: '意义较小，增量性工作',
                    1: '缺乏研究意义',
                },
            },
            {
                'name': '创新性',
                'code': 'NOVELTY',
                'guidelines': {
                    5: '提出全新理论框架或方法',
                    4: '有显著创新点',
                    3: '有一定创新性',
                    2: '创新性不足',
                    1: '无创新',
                },
            },
            {
                'name': '研究方法',
                'code': 'METHODOLOGY',
                'guidelines': {
                    5: '方法严谨，数据处理充分，稳健性强',
                    4: '方法得当，分析充分',
                    3: '方法基本合理',
                    2: '方法有明显缺陷',
                    1: '方法不当',
                },
            },
            {
                'name': '写作水平',
                'code': 'WRITING',
                'guidelines': {
                    5: '结构清晰，表达准确，逻辑严密',
                    4: '写作良好',
                    3: '写作一般',
                    2: '表达不清',
                    1: '写作极差',
                },
            },
        ],
    }

    @classmethod
    def review_anonymization(cls, knowledge_id, reviewer, decision, notes=''):
        """
        第二阶段人工审核

        :param knowledge_id: KnowledgeItem ID
        :param reviewer: User (编辑部)
        :param decision: APPROVED / REJECTED / PERMANENTLY_EXCLUDED
        :param notes: 审核备注
        :return: KnowledgeItem
        :raises ValueError: 条目不存在或状态不允许
        """
        try:
            item = KnowledgeItem.objects.get(knowledge_id=knowledge_id)
        except KnowledgeItem.DoesNotExist:
            raise ValueError(f'知识库条目 {knowledge_id} 不存在')

        # 状态校验：只有 PENDING_REVIEW 和 REJECTED 状态可审核
        allowed = [
            KnowledgeItem.AnonymizationStatus.PENDING_REVIEW,
            KnowledgeItem.AnonymizationStatus.REJECTED,
        ]
        if item.anonymization_status not in allowed:
            raise ValueError(f'当前状态 {item.anonymization_status} 不允许审核操作')

        now = tz.now()

        if decision == 'APPROVED':
            item.anonymization_status = KnowledgeItem.AnonymizationStatus.APPROVED
            item.archived_at = now  # 不可逆归档
        elif decision == 'REJECTED':
            item.anonymization_status = KnowledgeItem.AnonymizationStatus.REJECTED
        elif decision == 'PERMANENTLY_EXCLUDED':
            item.anonymization_status = KnowledgeItem.AnonymizationStatus.PERMANENTLY_EXCLUDED
        else:
            raise ValueError(f'无效的审核决策: {decision}')

        item.reviewed_by = reviewer
        item.reviewed_at = now
        item.review_notes = notes or ''  # 评审意见 V1.2 严重#5：审核备注落库
        item.save()

        logger.info(f'审核完成: ki={knowledge_id}, decision={decision}, reviewer={reviewer.email}')
        return item

    @classmethod
    def search(cls, query_params):
        """
        多条件组合检索

        :param query_params: dict (从 request.query_params 转换)
        :return: dict {count, page, total_pages, results, is_cold_start, cold_start_guide}
        """
        # 仅返回 APPROVED 条目
        qs = KnowledgeItem.objects.filter(
            anonymization_status=KnowledgeItem.AnonymizationStatus.APPROVED
        )

        # 取第一个值（query_params 是 dict of lists）
        def get_param(key):
            val = query_params.get(key)
            if isinstance(val, list):
                return val[0] if val else ''
            return val or ''

        keyword = get_param('keyword')
        subject_area = get_param('subject_area')
        manuscript_type = get_param('manuscript_type')
        final_decision = get_param('final_decision')
        recommendation = get_param('recommendation')
        score_range = get_param('score_range')
        date_start = get_param('date_start')
        date_end = get_param('date_end')

        # 关键词全文搜索（ilike）
        if keyword:
            qs = qs.filter(
                Q(anonymized_summary__icontains=keyword) |
                Q(keywords__icontains=keyword) |
                Q(tags__icontains=keyword) |
                Q(subject_area__icontains=keyword)
            )

        # 学科
        if subject_area:
            qs = qs.filter(subject_area=subject_area)

        # 类型
        if manuscript_type:
            qs = qs.filter(manuscript_type=manuscript_type)

        # 终审决策
        if final_decision:
            qs = qs.filter(final_decision=final_decision)

        # 推荐意见（搜索 anonymized_recommendations JSON 字段）
        if recommendation:
            qs = qs.filter(anonymized_recommendations__icontains=recommendation)

        # 评分区间
        if score_range:
            if score_range == 'high':
                qs = qs.filter(anonymized_dimensions__contains=[{'avg': 4}])  # 简化匹配
            elif score_range == 'mid_high':
                qs = qs.filter(anonymized_dimensions__contains=[{'avg': 3}])

        # 日期范围（按审稿年月）
        if date_start:
            try:
                year, month = date_start.split('-')
                qs = qs.filter(review_year__gte=int(year))
                if len(date_start) > 4:
                    qs = qs.filter(
                        Q(review_year__gt=int(year)) |
                        Q(review_year=int(year), review_month__gte=int(month))
                    )
            except (ValueError, IndexError):
                pass

        if date_end:
            try:
                year, month = date_end.split('-')
                qs = qs.filter(review_year__lte=int(year))
                if len(date_end) > 4:
                    qs = qs.filter(
                        Q(review_year__lt=int(year)) |
                        Q(review_year=int(year), review_month__lte=int(month))
                    )
            except (ValueError, IndexError):
                pass

        # 排序：默认相关度（简化为最新优先）
        sort_by = get_param('sort_by')
        if sort_by == 'score':
            qs = qs.order_by('-review_year', '-review_month')
        else:
            qs = qs.order_by('-created_at')

        # 分页
        try:
            page = int(get_param('page') or '1')
        except (TypeError, ValueError):
            page = 1
        if page < 1:
            page = 1
        per_page = 20

        total_count = qs.count()
        total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 0
        start = (page - 1) * per_page
        items = qs[start:start + per_page]

        from .serializers import KnowledgeItemBriefSerializer
        results = KnowledgeItemBriefSerializer(items, many=True).data

        # 冷启动降级
        is_cold_start = (total_count == 0)
        cold_start_guide = cls.get_cold_start_guide() if is_cold_start else None

        return {
            'count': total_count,
            'page': page,
            'total_pages': total_pages,
            'results': results,
            'is_cold_start': is_cold_start,
            'cold_start_guide': cold_start_guide,
        }

    @classmethod
    def get_detail(cls, knowledge_id, user, ip_address=None):
        """
        获取详情（记录访问日志）

        :param knowledge_id: KnowledgeItem ID
        :param user: User
        :param ip_address: 客户端IP
        :return: dict (KnowledgeItem 完整数据)
        :raises ValueError: 条目不存在
        """
        try:
            item = KnowledgeItem.objects.get(knowledge_id=knowledge_id)
        except KnowledgeItem.DoesNotExist:
            raise ValueError(f'知识库条目 {knowledge_id} 不存在')

        # 审稿人只能看 APPROVED 条目
        if user.is_reviewer and not user.is_editor:
            if item.anonymization_status != KnowledgeItem.AnonymizationStatus.APPROVED:
                raise ValueError(f'知识库条目 {knowledge_id} 不存在')

        # 记录访问日志
        AccessLog.objects.create(
            user=user,
            action='VIEW_KB_ITEM',
            target_id=knowledge_id,
            ip_address=ip_address,
        )

        from .serializers import KnowledgeItemSerializer
        return KnowledgeItemSerializer(item).data

    @classmethod
    def get_cold_start_guide(cls):
        """返回冷启动模板评分指引"""
        return cls.COLD_START_GUIDE

    @classmethod
    def export_data(cls, user, format='json'):
        """
        批量导出匿名化数据

        :param user: User（编辑部）
        :param format: 'json' 或 'csv'
        :return: list of dict（不含 source_task_id）
        """
        qs = KnowledgeItem.objects.filter(
            anonymization_status=KnowledgeItem.AnonymizationStatus.APPROVED
        ).order_by('-created_at')[:1000]

        data = []
        for item in qs:
            data.append({
                'knowledge_id': item.knowledge_id,
                'subject_area': item.subject_area,
                'manuscript_type': item.manuscript_type,
                'keywords': item.keywords,
                'review_year': item.review_year,
                'review_month': item.review_month,
                'review_mode': item.review_mode,
                'anonymized_dimensions': item.anonymized_dimensions,
                'anonymized_recommendations': item.anonymized_recommendations,
                'anonymized_summary': item.anonymized_summary,
                'template_info': item.template_info,
                'final_decision': item.final_decision,
                'tags': item.tags,
                'archived_at': item.archived_at.isoformat() if item.archived_at else None,
            })

        return data
