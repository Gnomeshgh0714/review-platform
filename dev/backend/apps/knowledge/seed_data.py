"""
审稿知识库种子数据 - 对应PRD §3.1.12 / S-01 冷启动策略

功能：
- init_seed_data()：初始化种子数据
  创建5-10条匿名化示例KnowledgeItem，覆盖经济学/管理学/统计学等学科，
  状态=APPROVED，确保冷启动期检索有基本命中率。

种子数据为示例性审稿意见（非真实数据），内容已完全匿名化。
可重复执行（幂等），已存在的种子数据不会重复创建。
"""
import logging

from django.utils import timezone

from .models import KnowledgeItem

logger = logging.getLogger(__name__)


def _make_seed_item(
    subject_area: str,
    manuscript_type: str,
    keywords: list,
    review_year: int,
    review_month: int,
    review_mode: str,
    dimensions: list,
    recommendations: dict,
    summary: str,
    template_info: dict,
    final_decision: str,
    tags: list,
    knowledge_id_suffix: str,
) -> KnowledgeItem:
    """创建单条种子KnowledgeItem（内部辅助函数）"""
    return KnowledgeItem(
        knowledge_id=f'KI-SEED-{knowledge_id_suffix}',
        source_task_id=f'SEED-{knowledge_id_suffix}',
        source_report=None,
        subject_area=subject_area,
        manuscript_type=manuscript_type,
        keywords=keywords,
        review_year=review_year,
        review_month=review_month,
        review_mode=review_mode,
        anonymized_dimensions=dimensions,
        anonymized_recommendations=recommendations,
        anonymized_summary=summary,
        template_info=template_info,
        final_decision=final_decision,
        tags=tags,
        anonymization_status=KnowledgeItem.AnonymizationStatus.APPROVED,
        pending_review_segments=[],
        archived_at=timezone.now(),
    )


def init_seed_data():
    """
    初始化种子数据

    创建8条匿名化示例KnowledgeItem，覆盖：
    - 经济学（宏观/微观/计量）
    - 管理学（战略管理/组织行为）
    - 统计学（贝叶斯/机器学习）
    - 金融学
    - 公共管理

    种子数据为示例性审稿意见（非真实数据），状态=APPROVED。
    可重复执行（幂等）。
    """
    # 幂等检查：已有种子数据则跳过
    if KnowledgeItem.objects.filter(knowledge_id__startswith='KI-SEED-').exists():
        logger.info('种子数据已存在，跳过初始化')
        return

    # 通用模板信息
    template_info = {
        'template_id': 'TPL-SEED-0001',
        'template_name': '通用四维审稿模板',
        'subject_area': '',
        'dimensions': [
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'description': '研究问题的学术价值与现实意义', 'minWords': 50},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'description': '理论创新、方法创新或数据创新', 'minWords': 50},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'description': '研究设计的合理性、方法的适当性', 'minWords': 50},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'description': '论文结构、逻辑表达、规范性', 'minWords': 50},
        ],
    }

    # ==================== 种子数据定义 ====================

    seed_items = []

    # 1. 经济学 - 宏观经济 - 接收
    seed_items.append(_make_seed_item(
        subject_area='经济学',
        manuscript_type='研究论文',
        keywords=['货币政策', '通货膨胀', '产出缺口', '宏观计量'],
        review_year=2025,
        review_month=6,
        review_mode='DOUBLE_BLIND',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 5, 'comment': '该研究对货币政策传导机制的分析具有重要理论价值，有助于理解通胀动态。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '研究问题有较好意义，对货币政策制定有参考价值。'},
                {'reviewerLabel': '审稿人C', 'score': 5, 'comment': '选题切中当前宏观经济热点，有较强现实意义。'},
            ]},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '在产出缺口度量方法上有一定创新，但理论框架部分沿用已有文献。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '方法创新明显，引入时变参数模型丰富了分析视角。'},
                {'reviewerLabel': '审稿人C', 'score': 5, 'comment': '创新性突出，将贝叶斯方法应用于政策传导分析具有新意。'},
            ]},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 5, 'comment': '研究设计严谨，数据来源可靠，计量方法适当。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '方法基本适当，稳健性检验可进一步补充。'},
                {'reviewerLabel': '审稿人C', 'score': 5, 'comment': '方法论扎实，模型设定合理。'},
            ]},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '结构清晰，逻辑通顺，个别表述可优化。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '写作规范，图表标注准确。'},
                {'reviewerLabel': '审稿人C', 'score': 5, 'comment': '写作水平高，表达准确流畅。'},
            ]},
        ],
        recommendations={'ACCEPT': 2, 'MINOR_REVISION': 1, 'MAJOR_REVISION': 0, 'REJECT': 0, 'total': 3},
        summary=(
            '【稿件信息】经济学稿件（关键词：货币政策、通货膨胀、产出缺口）\n'
            '【稿件类型】研究论文\n'
            '【审稿模式】双盲\n\n'
            '【维度评分对比】\n'
            '  研究意义 - 审稿人A: 5, 审稿人B: 4, 审稿人C: 5\n'
            '  创新性 - 审稿人A: 4, 审稿人B: 4, 审稿人C: 5\n'
            '  研究方法 - 审稿人A: 5, 审稿人B: 4, 审稿人C: 5\n'
            '  写作水平 - 审稿人A: 4, 审稿人B: 4, 审稿人C: 5\n\n'
            '【推荐意见分布】\n'
            '  接收: 2票\n  小修: 1票\n  总计: 3位审稿人\n\n'
            '【系统终审建议】\n  匹配规则: Rule-2\n  结论: 倾向接收\n\n'
            '【终审决策】ACCEPT'
        ),
        template_info=template_info,
        final_decision='ACCEPT',
        tags=['经济学', '研究论文', '货币政策', '通货膨胀', '产出缺口', '评分区间:高(4.5-5)', '推荐接收'],
        knowledge_id_suffix='0001',
    ))

    # 2. 经济学 - 微观经济 - 小修
    seed_items.append(_make_seed_item(
        subject_area='经济学',
        manuscript_type='研究论文',
        keywords=['博弈论', '产业组织', '市场结构', '定价策略'],
        review_year=2025,
        review_month=5,
        review_mode='DOUBLE_BLIND',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '研究寡头市场定价策略有较好的理论贡献。'},
                {'reviewerLabel': '审稿人B', 'score': 3, 'comment': '意义一般，已有类似研究较多。'},
            ]},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '模型设定有新意，引入动态博弈框架。'},
                {'reviewerLabel': '审稿人B', 'score': 3, 'comment': '创新性一般，核心框架沿用已有文献。'},
            ]},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '博弈模型设定严谨，求解方法适当。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '方法论扎实，但实证部分可加强。'},
            ]},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '逻辑清晰，表达准确。'},
                {'reviewerLabel': '审稿人B', 'score': 3, 'comment': '部分章节表述可优化。'},
            ]},
        ],
        recommendations={'ACCEPT': 1, 'MINOR_REVISION': 1, 'MAJOR_REVISION': 0, 'REJECT': 0, 'total': 2},
        summary=(
            '【稿件信息】经济学稿件（关键词：博弈论、产业组织、市场结构）\n'
            '【稿件类型】研究论文\n'
            '【审稿模式】双盲\n\n'
            '【维度评分对比】\n'
            '  研究意义 - 审稿人A: 4, 审稿人B: 3\n'
            '  创新性 - 审稿人A: 4, 审稿人B: 3\n'
            '  研究方法 - 审稿人A: 4, 审稿人B: 4\n'
            '  写作水平 - 审稿人A: 4, 审稿人B: 3\n\n'
            '【推荐意见分布】\n  接收: 1票\n  小修: 1票\n  总计: 2位审稿人\n\n'
            '【系统终审建议】\n  匹配规则: Rule-2\n  结论: 倾向接收（仅供参考，建议人工判断）\n\n'
            '【终审决策】MINOR_REVISION'
        ),
        template_info=template_info,
        final_decision='MINOR_REVISION',
        tags=['经济学', '研究论文', '博弈论', '产业组织', '市场结构', '评分区间:中高(3.5-4.5)', '推荐接收'],
        knowledge_id_suffix='0002',
    ))

    # 3. 管理学 - 战略管理 - 大修
    seed_items.append(_make_seed_item(
        subject_area='管理学',
        manuscript_type='研究论文',
        keywords=['战略管理', '动态能力', '数字化转型', '竞争优势'],
        review_year=2025,
        review_month=4,
        review_mode='SINGLE_BLIND',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '数字化转型背景下的动态能力研究有现实意义。'},
                {'reviewerLabel': '审稿人B', 'score': 3, 'comment': '选题有意义但切入点不够新颖。'},
                {'reviewerLabel': '审稿人C', 'score': 4, 'comment': '对战略管理理论与实践有较好贡献。'},
            ]},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 3, 'comment': '理论创新不足，动态能力框架已有大量研究。'},
                {'reviewerLabel': '审稿人B', 'score': 2, 'comment': '创新性较低，多为已有研究的整合。'},
                {'reviewerLabel': '审稿人C', 'score': 3, 'comment': '在数字化情境下有一定拓展，但创新有限。'},
            ]},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 3, 'comment': '案例研究方法基本可行，但样本量偏少。'},
                {'reviewerLabel': '审稿人B', 'score': 2, 'comment': '研究设计有缺陷，缺乏系统性的案例分析框架。'},
                {'reviewerLabel': '审稿人C', 'score': 3, 'comment': '方法适当但可深化，建议增加对比案例。'},
            ]},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 3, 'comment': '结构基本合理，部分章节逻辑不够连贯。'},
                {'reviewerLabel': '审稿人B', 'score': 2, 'comment': '写作欠佳，图表标注不规范。'},
                {'reviewerLabel': '审稿人C', 'score': 4, 'comment': '表达清楚，文献综述部分较完整。'},
            ]},
        ],
        recommendations={'ACCEPT': 0, 'MINOR_REVISION': 0, 'MAJOR_REVISION': 2, 'REJECT': 1, 'total': 3},
        summary=(
            '【稿件信息】管理学稿件（关键词：战略管理、动态能力、数字化转型）\n'
            '【稿件类型】研究论文\n'
            '【审稿模式】单盲\n\n'
            '【维度评分对比】\n'
            '  研究意义 - 审稿人A: 4, 审稿人B: 3, 审稿人C: 4\n'
            '  创新性 - 审稿人A: 3, 审稿人B: 2, 审稿人C: 3\n'
            '  研究方法 - 审稿人A: 3, 审稿人B: 2, 审稿人C: 3\n'
            '  写作水平 - 审稿人A: 3, 审稿人B: 2, 审稿人C: 4\n\n'
            '【推荐意见分布】\n  大修: 2票\n  拒稿: 1票\n  总计: 3位审稿人\n\n'
            '【系统终审建议】\n  匹配规则: Rule-5\n  结论: 建议大修\n\n'
            '【终审决策】MAJOR_REVISION'
        ),
        template_info=template_info,
        final_decision='MAJOR_REVISION',
        tags=['管理学', '研究论文', '战略管理', '动态能力', '数字化转型', '评分区间:中(2.5-3.5)', '推荐大修'],
        knowledge_id_suffix='0003',
    ))

    # 4. 管理学 - 组织行为 - 接收
    seed_items.append(_make_seed_item(
        subject_area='管理学',
        manuscript_type='研究论文',
        keywords=['组织行为', '领导力', '员工敬业度', '心理资本'],
        review_year=2025,
        review_month=3,
        review_mode='DOUBLE_BLIND',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '领导力与员工敬业度的关系研究有实践价值。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '对组织行为学研究有贡献，心理资本视角有新意。'},
            ]},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '引入心理资本作为中介变量有一定创新。'},
                {'reviewerLabel': '审稿人B', 'score': 5, 'comment': '创新性突出，整合了领导力与积极心理学视角。'},
            ]},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '问卷调查方法规范，样本代表性较好。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '结构方程模型运用适当，检验充分。'},
            ]},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '写作规范，逻辑清晰。'},
                {'reviewerLabel': '审稿人B', 'score': 5, 'comment': '表达准确，文献综述全面。'},
            ]},
        ],
        recommendations={'ACCEPT': 2, 'MINOR_REVISION': 0, 'MAJOR_REVISION': 0, 'REJECT': 0, 'total': 2},
        summary=(
            '【稿件信息】管理学稿件（关键词：组织行为、领导力、员工敬业度）\n'
            '【稿件类型】研究论文\n'
            '【审稿模式】双盲\n\n'
            '【维度评分对比】\n'
            '  研究意义 - 审稿人A: 4, 审稿人B: 4\n'
            '  创新性 - 审稿人A: 4, 审稿人B: 5\n'
            '  研究方法 - 审稿人A: 4, 审稿人B: 4\n'
            '  写作水平 - 审稿人A: 4, 审稿人B: 5\n\n'
            '【推荐意见分布】\n  接收: 2票\n  总计: 2位审稿人\n\n'
            '【系统终审建议】\n  匹配规则: Rule-1\n  结论: 建议接收（仅供参考，建议人工判断）\n\n'
            '【终审决策】ACCEPT'
        ),
        template_info=template_info,
        final_decision='ACCEPT',
        tags=['管理学', '研究论文', '组织行为', '领导力', '员工敬业度', '评分区间:高(4.5-5)', '推荐接收'],
        knowledge_id_suffix='0004',
    ))

    # 5. 统计学 - 贝叶斯方法 - 小修
    seed_items.append(_make_seed_item(
        subject_area='统计学',
        manuscript_type='研究论文',
        keywords=['贝叶斯推断', '马尔可夫链蒙特卡洛', '变量选择', '高维数据'],
        review_year=2025,
        review_month=2,
        review_mode='DOUBLE_BLIND',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 5, 'comment': '高维贝叶斯变量选择方法有重要方法论意义。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '研究问题有意义，对实际数据分析有参考价值。'},
                {'reviewerLabel': '审稿人C', 'score': 4, 'comment': '方法论贡献明确，有较好应用前景。'},
            ]},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 5, 'comment': '提出新的先验设定方法，创新性显著。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '在MCMC算法改进上有明确创新。'},
                {'reviewerLabel': '审稿人C', 'score': 4, 'comment': '创新性较好，但部分思路已有文献涉及。'},
            ]},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 5, 'comment': '数学推导严谨，模拟实验设计充分。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '方法适当，收敛性诊断可进一步讨论。'},
                {'reviewerLabel': '审稿人C', 'score': 4, 'comment': '方法论扎实，建议补充实际数据应用。'},
            ]},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '数学表达准确，结构清晰。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '写作规范，个别符号标注可统一。'},
                {'reviewerLabel': '审稿人C', 'score': 5, 'comment': '写作水平高，逻辑严密。'},
            ]},
        ],
        recommendations={'ACCEPT': 1, 'MINOR_REVISION': 2, 'MAJOR_REVISION': 0, 'REJECT': 0, 'total': 3},
        summary=(
            '【稿件信息】统计学稿件（关键词：贝叶斯推断、马尔可夫链蒙特卡洛、变量选择）\n'
            '【稿件类型】研究论文\n'
            '【审稿模式】双盲\n\n'
            '【维度评分对比】\n'
            '  研究意义 - 审稿人A: 5, 审稿人B: 4, 审稿人C: 4\n'
            '  创新性 - 审稿人A: 5, 审稿人B: 4, 审稿人C: 4\n'
            '  研究方法 - 审稿人A: 5, 审稿人B: 4, 审稿人C: 4\n'
            '  写作水平 - 审稿人A: 4, 审稿人B: 4, 审稿人C: 5\n\n'
            '【推荐意见分布】\n  接收: 1票\n  小修: 2票\n  总计: 3位审稿人\n\n'
            '【系统终审建议】\n  匹配规则: Rule-2\n  结论: 倾向接收\n\n'
            '【终审决策】MINOR_REVISION'
        ),
        template_info=template_info,
        final_decision='MINOR_REVISION',
        tags=['统计学', '研究论文', '贝叶斯推断', '马尔可夫链蒙特卡洛', '变量选择', '评分区间:高(4.5-5)', '推荐接收'],
        knowledge_id_suffix='0005',
    ))

    # 6. 统计学 - 机器学习 - 大修
    seed_items.append(_make_seed_item(
        subject_area='统计学',
        manuscript_type='研究论文',
        keywords=['机器学习', '因果推断', '深度学习', '可解释性'],
        review_year=2025,
        review_month=1,
        review_mode='DOUBLE_BLIND',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '机器学习与因果推断结合是重要研究方向。'},
                {'reviewerLabel': '审稿人B', 'score': 3, 'comment': '选题有意义，但贡献需要进一步明确。'},
            ]},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '将可解释性方法引入因果推断有创新。'},
                {'reviewerLabel': '审稿人B', 'score': 3, 'comment': '创新性一般，与近期已有研究有重叠。'},
            ]},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 3, 'comment': '方法设计有改进空间，理论证明不够完整。'},
                {'reviewerLabel': '审稿人B', 'score': 2, 'comment': '研究方法存在缺陷，假设条件过强。'},
            ]},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 3, 'comment': '结构基本可行，部分内容表述不清。'},
                {'reviewerLabel': '审稿人B', 'score': 3, 'comment': '写作一般，数学符号不统一。'},
            ]},
        ],
        recommendations={'ACCEPT': 0, 'MINOR_REVISION': 0, 'MAJOR_REVISION': 2, 'REJECT': 0, 'total': 2},
        summary=(
            '【稿件信息】统计学稿件（关键词：机器学习、因果推断、深度学习）\n'
            '【稿件类型】研究论文\n'
            '【审稿模式】双盲\n\n'
            '【维度评分对比】\n'
            '  研究意义 - 审稿人A: 4, 审稿人B: 3\n'
            '  创新性 - 审稿人A: 4, 审稿人B: 3\n'
            '  研究方法 - 审稿人A: 3, 审稿人B: 2\n'
            '  写作水平 - 审稿人A: 3, 审稿人B: 3\n\n'
            '【推荐意见分布】\n  大修: 2票\n  总计: 2位审稿人\n\n'
            '【系统终审建议】\n  匹配规则: Rule-5\n  结论: 建议大修（仅供参考，建议人工判断）\n\n'
            '【终审决策】MAJOR_REVISION'
        ),
        template_info=template_info,
        final_decision='MAJOR_REVISION',
        tags=['统计学', '研究论文', '机器学习', '因果推断', '深度学习', '评分区间:中(2.5-3.5)', '推荐大修'],
        knowledge_id_suffix='0006',
    ))

    # 7. 金融学 - 资产定价 - 拒稿
    seed_items.append(_make_seed_item(
        subject_area='金融学',
        manuscript_type='研究论文',
        keywords=['资产定价', '因子模型', '市场异象', '风险溢价'],
        review_year=2024,
        review_month=12,
        review_mode='DOUBLE_BLIND',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 3, 'comment': '因子模型研究已有大量文献，意义有限。'},
                {'reviewerLabel': '审稿人B', 'score': 2, 'comment': '研究问题不明确，贡献难以辨识。'},
                {'reviewerLabel': '审稿人C', 'score': 3, 'comment': '选题一般，市场异象的解释力不足。'},
            ]},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 2, 'comment': '创新性不足，核心方法沿用已有框架。'},
                {'reviewerLabel': '审稿人B', 'score': 1, 'comment': '无实质创新，为已有研究的简单复制。'},
                {'reviewerLabel': '审稿人C', 'score': 2, 'comment': '创新性较低，缺乏新视角。'},
            ]},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 2, 'comment': '研究设计有缺陷，数据选择存在偏误。'},
                {'reviewerLabel': '审稿人B', 'score': 1, 'comment': '方法错误，统计检验不充分。'},
                {'reviewerLabel': '审稿人C', 'score': 2, 'comment': '方法不当，稳健性检验缺失。'},
            ]},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 3, 'comment': '结构基本合理，表述一般。'},
                {'reviewerLabel': '审稿人B', 'score': 2, 'comment': '逻辑混乱，图表错误较多。'},
                {'reviewerLabel': '审稿人C', 'score': 3, 'comment': '写作水平中等，部分章节需重写。'},
            ]},
        ],
        recommendations={'ACCEPT': 0, 'MINOR_REVISION': 0, 'MAJOR_REVISION': 0, 'REJECT': 3, 'total': 3},
        summary=(
            '【稿件信息】金融学稿件（关键词：资产定价、因子模型、市场异象）\n'
            '【稿件类型】研究论文\n'
            '【审稿模式】双盲\n\n'
            '【维度评分对比】\n'
            '  研究意义 - 审稿人A: 3, 审稿人B: 2, 审稿人C: 3\n'
            '  创新性 - 审稿人A: 2, 审稿人B: 1, 审稿人C: 2\n'
            '  研究方法 - 审稿人A: 2, 审稿人B: 1, 审稿人C: 2\n'
            '  写作水平 - 审稿人A: 3, 审稿人B: 2, 审稿人C: 3\n\n'
            '【推荐意见分布】\n  拒稿: 3票\n  总计: 3位审稿人\n\n'
            '【系统终审建议】\n  匹配规则: Rule-6\n  结论: 建议拒稿\n\n'
            '【终审决策】REJECT'
        ),
        template_info=template_info,
        final_decision='REJECT',
        tags=['金融学', '研究论文', '资产定价', '因子模型', '市场异象', '评分区间:低(<2.5)', '推荐拒稿'],
        knowledge_id_suffix='0007',
    ))

    # 8. 公共管理 - 政策评估 - 小修
    seed_items.append(_make_seed_item(
        subject_area='公共管理',
        manuscript_type='研究论文',
        keywords=['政策评估', '双重差分', '政策效应', '准自然实验'],
        review_year=2024,
        review_month=11,
        review_mode='SINGLE_BLIND',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '政策效应评估有较强的现实意义。'},
                {'reviewerLabel': '审稿人B', 'score': 5, 'comment': '选题重要，对公共政策制定有参考价值。'},
            ]},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 3, 'comment': '双重差分方法应用规范，但方法本身创新有限。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '在政策评估框架上有一定拓展。'},
            ]},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '准自然实验设计合理，识别策略清晰。'},
                {'reviewerLabel': '审稿人B', 'score': 4, 'comment': '方法适当，平行趋势检验充分。'},
            ]},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'scores': [
                {'reviewerLabel': '审稿人A', 'score': 4, 'comment': '写作规范，逻辑清晰。'},
                {'reviewerLabel': '审稿人B', 'score': 5, 'comment': '表达准确，图表规范。'},
            ]},
        ],
        recommendations={'ACCEPT': 0, 'MINOR_REVISION': 2, 'MAJOR_REVISION': 0, 'REJECT': 0, 'total': 2},
        summary=(
            '【稿件信息】公共管理稿件（关键词：政策评估、双重差分、政策效应）\n'
            '【稿件类型】研究论文\n'
            '【审稿模式】单盲\n\n'
            '【维度评分对比】\n'
            '  研究意义 - 审稿人A: 4, 审稿人B: 5\n'
            '  创新性 - 审稿人A: 3, 审稿人B: 4\n'
            '  研究方法 - 审稿人A: 4, 审稿人B: 4\n'
            '  写作水平 - 审稿人A: 4, 审稿人B: 5\n\n'
            '【推荐意见分布】\n  小修: 2票\n  总计: 2位审稿人\n\n'
            '【系统终审建议】\n  匹配规则: Rule-2\n  结论: 倾向接收（仅供参考，建议人工判断）\n\n'
            '【终审决策】MINOR_REVISION'
        ),
        template_info=template_info,
        final_decision='MINOR_REVISION',
        tags=['公共管理', '研究论文', '政策评估', '双重差分', '政策效应', '评分区间:中高(3.5-4.5)', '推荐接收'],
        knowledge_id_suffix='0008',
    ))

    # ==================== 批量创建 ====================

    created = []
    for item in seed_items:
        # 绕过model.save()的自动ID生成，直接使用预设的KI-SEED-xxxx
        item.save()
        created.append(item)

    logger.info('种子数据初始化完成，共创建 %d 条', len(created))
    print(f'审稿知识库种子数据已创建：{len(created)}条')
    return created
