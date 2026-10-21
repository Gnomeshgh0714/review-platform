"""
审稿意见汇总服务模块 - 对应PRD §3.1.6 审稿意见汇总功能

功能：
1. 意见聚合：按维度对齐多审稿人评分和文字（同一模板直接对齐）
2. 分歧标注：max-min≥3严重(红)、=2明显(黄)、≤1一致(绿)
3. 一致点分析：区分正向一致（高分一致）和负向一致（低分一致）
4. 规则引擎：7条规则+优先级链式匹配
5. 汇总报告生成：触发状态转换 SUBMITTED -> SUMMARIZED
"""
import math
import logging
from collections import Counter
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.tasks.models import ReviewTask, Template
from apps.forms.models import ReviewOpinion
from apps.summaries.models import SummaryReport
from apps.tasks.state_machine import StateMachineService, StateMachineError
from apps.notifications.services import NotificationService

logger = logging.getLogger(__name__)


class SummaryService:
    """审稿意见汇总服务"""

    # ==================== 规则定义 ====================

    # 推荐意见常量（与 ReviewOpinion.Recommendation 对齐）
    ACCEPT = 'ACCEPT'
    MINOR_REVISION = 'MINOR_REVISION'
    MAJOR_REVISION = 'MAJOR_REVISION'
    REJECT = 'REJECT'

    # 全部推荐类型
    ALL_RECOMMENDATIONS = [ACCEPT, MINOR_REVISION, MAJOR_REVISION, REJECT]

    # 规则结论文案
    RULE_CONCLUSIONS = {
        'Rule-7': '严重分歧需讨论',
        'Rule-4': '分歧需讨论',
        'Rule-6': '建议拒稿',
        'Rule-5': '建议大修',
        'Rule-3': '倾向接收但需讨论',
        'Rule-2': '倾向接收',
        'Rule-1': '建议接收',
    }

    # ==================== 1. 意见聚合 ====================

    @staticmethod
    def aggregate_opinions(task: ReviewTask) -> dict:
        """
        聚合多审稿人意见

        - 按维度对齐评分和文字（同一模板直接对齐）
        - 统计推荐分布
        - 分类汇总修改建议
        - 汇集综合评语

        :param task: ReviewTask 审稿任务
        :return: dict 包含 opinion_ids, dimension_comparison,
                 recommendation_distribution, revision_suggestions_summary, overall_comments
        """
        # 获取该任务下所有已提交的审稿意见（P0仅处理第1轮）
        opinions = list(
            ReviewOpinion.objects.filter(
                task=task,
                status='SUBMITTED',
                round=1,
            ).select_related('reviewer').order_by('submitted_at')
        )

        if not opinions:
            return {
                'opinion_ids': [],
                'dimension_comparison': [],
                'recommendation_distribution': {
                    'ACCEPT': 0,
                    'MINOR_REVISION': 0,
                    'MAJOR_REVISION': 0,
                    'REJECT': 0,
                    'total': 0,
                },
                'revision_suggestions_summary': {'by_dimension': {}, 'all': []},
                'overall_comments': [],
            }

        opinion_ids = [op.opinion_id for op in opinions]

        # --- 获取模板维度配置（用于维度名对齐） ---
        dimension_name_map = {}
        try:
            template = Template.objects.get(template_id=task.template_id)
            for dim in template.dimensions:
                dimension_name_map[dim['dimensionId']] = dim.get('dimensionName', dim['dimensionId'])
        except Template.DoesNotExist:
            logger.warning('模板 %s 不存在，维度名将使用 dimensionId', task.template_id)

        # 如果模板没配置维度，从意见中收集
        if not dimension_name_map:
            for op in opinions:
                for ds in (op.dimension_scores or []):
                    dim_id = ds.get('dimensionId', '')
                    if dim_id and dim_id not in dimension_name_map:
                        dimension_name_map[dim_id] = dim_id

        # --- 按维度对齐评分和文字 ---
        dimension_comparison = []
        for dim_id, dim_name in dimension_name_map.items():
            dim_data = {
                'dimensionId': dim_id,
                'dimensionName': dim_name,
                'scores': [],
            }
            for op in opinions:
                # 在该意见中查找对应维度的评分
                score_entry = None
                for ds in (op.dimension_scores or []):
                    if ds.get('dimensionId') == dim_id:
                        score_entry = ds
                        break
                dim_data['scores'].append({
                    'reviewerId': op.reviewer.user_id,
                    'reviewerName': op.reviewer.name,
                    'opinionId': op.opinion_id,
                    'score': score_entry.get('score') if score_entry else None,
                    'comment': score_entry.get('comment', '') if score_entry else '',
                })
            dimension_comparison.append(dim_data)

        # --- 统计推荐分布 ---
        rec_counter = Counter(op.recommendation for op in opinions)
        recommendation_distribution = {
            'ACCEPT': rec_counter.get(SummaryService.ACCEPT, 0),
            'MINOR_REVISION': rec_counter.get(SummaryService.MINOR_REVISION, 0),
            'MAJOR_REVISION': rec_counter.get(SummaryService.MAJOR_REVISION, 0),
            'REJECT': rec_counter.get(SummaryService.REJECT, 0),
            'total': len(opinions),
        }

        # --- 分类汇总修改建议 ---
        # revision_suggestions 格式一般为 list[str] 或 list[{dimensionId, suggestion}]
        by_dimension = {}
        all_suggestions = []
        for op in opinions:
            for sug in (op.revision_suggestions or []):
                if isinstance(sug, dict):
                    dim_id = sug.get('dimensionId', 'GENERAL')
                    text = sug.get('suggestion', sug.get('text', str(sug)))
                else:
                    dim_id = 'GENERAL'
                    text = str(sug)
                by_dimension.setdefault(dim_id, []).append({
                    'reviewerName': op.reviewer.name,
                    'reviewerId': op.reviewer.user_id,
                    'suggestion': text,
                })
                all_suggestions.append({
                    'reviewerName': op.reviewer.name,
                    'reviewerId': op.reviewer.user_id,
                    'dimensionId': dim_id,
                    'suggestion': text,
                })

        revision_suggestions_summary = {
            'by_dimension': by_dimension,
            'all': all_suggestions,
        }

        # --- 汇集综合评语 ---
        overall_comments = [
            {
                'reviewerId': op.reviewer.user_id,
                'reviewerName': op.reviewer.name,
                'opinionId': op.opinion_id,
                'recommendation': op.recommendation,
                'recommendationDisplay': op.get_recommendation_display(),
                'comment': op.overall_comment,
            }
            for op in opinions
        ]

        return {
            'opinion_ids': opinion_ids,
            'dimension_comparison': dimension_comparison,
            'recommendation_distribution': recommendation_distribution,
            'revision_suggestions_summary': revision_suggestions_summary,
            'overall_comments': overall_comments,
        }

    # ==================== 2. 分歧标注 ====================

    @staticmethod
    def detect_conflicts(dimension_comparison: list) -> list:
        """
        分歧标注

        - max-min ≥ 3：严重(红)
        - max-min = 2：明显(黄)
        - max-min ≤ 1：一致(绿)，不纳入分歧列表

        每个分歧点附带分布信息（如"4/5位评分5分"）

        :param dimension_comparison: 维度对比数据（aggregate_opinions 输出）
        :return: 分歧点列表
        """
        conflict_points = []

        for dim in dimension_comparison:
            scores_raw = [s['score'] for s in dim['scores'] if s['score'] is not None]
            if len(scores_raw) < 2:
                continue  # 少于2个有效评分无法判定分歧

            max_score = max(scores_raw)
            min_score = min(scores_raw)
            diff = max_score - min_score

            # diff <= 1 视为一致，不纳入分歧列表
            if diff <= 1:
                continue

            # 判定级别
            if diff >= 3:
                level = 'SEVERE'
                level_label = '严重'
                color = 'red'
            elif diff == 2:
                level = 'MODERATE'
                level_label = '明显'
                color = 'yellow'
            else:
                continue

            # 评分分布统计
            score_counter = Counter(scores_raw)
            total = len(scores_raw)
            score_distribution = {str(k): v for k, v in sorted(score_counter.items(), reverse=True)}

            # 生成分布文本
            dist_parts = []
            for score_val, count in sorted(score_counter.items(), reverse=True):
                dist_parts.append(f'{count}/{total}位评分{score_val}分')
            distribution_text = '，'.join(dist_parts)

            conflict_points.append({
                'dimensionId': dim['dimensionId'],
                'dimensionName': dim['dimensionName'],
                'level': level,
                'levelLabel': level_label,
                'color': color,
                'maxScore': max_score,
                'minScore': min_score,
                'diff': diff,
                'scoreDistribution': score_distribution,
                'distributionText': distribution_text,
            })

        return conflict_points

    # ==================== 3. 一致点分析 ====================

    @staticmethod
    def analyze_consensus(dimension_comparison: list) -> list:
        """
        一致点分析

        区分正向一致（高分一致）和负向一致（低分一致）：
        - 正向一致：max-min ≤ 1 且平均分 ≥ 4
        - 负向一致：max-min ≤ 1 且平均分 ≤ 2

        :param dimension_comparison: 维度对比数据（aggregate_opinions 输出）
        :return: 一致点列表
        """
        consensus_points = []

        for dim in dimension_comparison:
            scores_raw = [s['score'] for s in dim['scores'] if s['score'] is not None]
            if len(scores_raw) < 2:
                continue

            max_score = max(scores_raw)
            min_score = min(scores_raw)
            diff = max_score - min_score

            # 仅分析一致情况（diff <= 1）
            if diff > 1:
                continue

            avg_score = sum(scores_raw) / len(scores_raw)

            # 判定正向/负向一致
            if avg_score >= 4:
                consensus_type = 'POSITIVE'
                type_label = '正向一致'
            elif avg_score <= 2:
                consensus_type = 'NEGATIVE'
                type_label = '负向一致'
            else:
                # 平均分在2-4之间（不含端点），虽一致但既非高分也非低分，跳过
                continue

            # 评分分布统计
            score_counter = Counter(scores_raw)
            total = len(scores_raw)
            score_distribution = {str(k): v for k, v in sorted(score_counter.items(), reverse=True)}

            dist_parts = []
            for score_val, count in sorted(score_counter.items(), reverse=True):
                dist_parts.append(f'{count}/{total}位评分{score_val}分')
            distribution_text = '，'.join(dist_parts)

            consensus_points.append({
                'dimensionId': dim['dimensionId'],
                'dimensionName': dim['dimensionName'],
                'type': consensus_type,
                'typeLabel': type_label,
                'avgScore': round(avg_score, 2),
                'maxScore': max_score,
                'minScore': min_score,
                'diff': diff,
                'scoreDistribution': score_distribution,
                'distributionText': distribution_text,
            })

        return consensus_points

    # ==================== 4. 规则引擎匹配 ====================

    @staticmethod
    def match_rule(recommendation_distribution: dict, reviewer_count: int) -> dict:
        """
        规则引擎匹配 - 按优先级链式匹配

        优先级从高到低：Rule-7 > Rule-4 > Rule-6 > Rule-5 > Rule-3 > Rule-2 > Rule-1

        规则定义：
        - Rule-7: 接收与拒稿并存 -> 严重分歧需讨论
        - Rule-4: 小修+大修+拒稿分散无接收 / 接收+小修+大修分散无拒稿 -> 分歧需讨论
        - Rule-6: 多数(≥半数)拒稿 -> 建议拒稿
        - Rule-5: 多数大修 -> 建议大修
        - Rule-3: 多数接收/小修+有大修或拒稿 -> 倾向接收但需讨论
        - Rule-2: 多数(≥半数)接收/小修 -> 倾向接收
        - Rule-1: 全票接收 -> 建议接收

        "多数" = count >= ceil(total / 2)
        1-2位审稿人时标注"仅供参考，建议人工判断"

        :param recommendation_distribution: 推荐意见分布
               {ACCEPT: int, MINOR_REVISION: int, MAJOR_REVISION: int, REJECT: int, total: int}
        :param reviewer_count: 审稿人总数
        :return: {matchedRuleId, conclusion, advisoryOnly}
        """
        accept = recommendation_distribution.get('ACCEPT', 0)
        minor = recommendation_distribution.get('MINOR_REVISION', 0)
        major = recommendation_distribution.get('MAJOR_REVISION', 0)
        reject = recommendation_distribution.get('REJECT', 0)
        total = reviewer_count or recommendation_distribution.get('total', 0)

        if total == 0:
            return {
                'matchedRuleId': None,
                'conclusion': '无审稿意见，无法匹配规则',
                'advisoryOnly': False,
            }

        # "多数"阈值：count >= ceil(total / 2)
        majority_threshold = math.ceil(total / 2)

        # 是否为1-2位审稿人（标注仅供参考）
        advisory_only = total <= 2

        matched_rule_id = None

        # ===== 按优先级顺序链式匹配 =====

        # Rule-4辅助条件预计算
        # "分散" = 三种类型都存在，且没有任何一种构成多数
        # 条件A: 小修+大修+拒稿分散无接收（三者都有，无接收，无多数）
        # 条件B: 接收+小修+大修分散无拒稿（三者都有，无拒稿，无多数）
        cond_a = (accept == 0 and minor > 0 and major > 0 and reject > 0
                  and minor < majority_threshold
                  and major < majority_threshold
                  and reject < majority_threshold)
        cond_b = (reject == 0 and accept > 0 and minor > 0 and major > 0
                  and accept < majority_threshold
                  and minor < majority_threshold
                  and major < majority_threshold)

        # Rule-7(最高): 接收与拒稿并存 -> 严重分歧需讨论
        if accept > 0 and reject > 0:
            matched_rule_id = 'Rule-7'

        # Rule-4: 分散（两种子条件，无任何一种构成多数）
        elif cond_a or cond_b:
            matched_rule_id = 'Rule-4'

        # Rule-6: 多数(≥半数)拒稿 -> 建议拒稿
        elif reject >= majority_threshold:
            matched_rule_id = 'Rule-6'

        # Rule-5: 多数大修 -> 建议大修
        elif major >= majority_threshold:
            matched_rule_id = 'Rule-5'

        # Rule-3: 多数接收/小修 + 有大修或拒稿 -> 倾向接收但需讨论
        elif (accept + minor) >= majority_threshold and (major > 0 or reject > 0):
            matched_rule_id = 'Rule-3'

        # Rule-2: 多数(≥半数)接收/小修（排除全票接收的情况） -> 倾向接收
        elif (accept + minor) >= majority_threshold and accept < total:
            matched_rule_id = 'Rule-2'

        # Rule-1(最低): 全票接收 -> 建议接收
        elif accept == total:
            matched_rule_id = 'Rule-1'

        # 兜底：无规则匹配（理论上不应发生）
        else:
            matched_rule_id = 'Rule-0'
            return {
                'matchedRuleId': 'Rule-0',
                'conclusion': '无法自动判定，建议人工讨论',
                'advisoryOnly': advisory_only,
                'note': '现有规则未覆盖此推荐分布场景',
            }

        conclusion = SummaryService.RULE_CONCLUSIONS.get(matched_rule_id, '')

        # 1-2位审稿人追加标注
        if advisory_only:
            conclusion = f'{conclusion}（仅供参考，建议人工判断）'

        return {
            'matchedRuleId': matched_rule_id,
            'conclusion': conclusion,
            'advisoryOnly': advisory_only,
        }

    # ==================== 5. 生成汇总报告 ====================

    @staticmethod
    @transaction.atomic
    def generate_report(task: ReviewTask, operator_user=None) -> SummaryReport:
        """
        生成完整汇总报告

        流程：聚合意见 -> 分歧标注 -> 一致点分析 -> 规则匹配 -> 保存报告 -> 状态转换

        状态转换：SUBMITTED -> SUMMARIZED
        触发通知：通知编辑部汇总报告已生成

        :param task: ReviewTask 审稿任务
        :param operator_user: 操作人（编辑部用户）
        :return: SummaryReport 汇总报告
        :raises StateMachineError: 状态转换失败
        """
        # 校验任务状态
        if task.status != 'SUBMITTED':
            raise StateMachineError(
                f'仅已提交(SUBMITTED)状态可生成汇总报告，当前状态: {task.status}'
            )

        # 1. 聚合意见
        aggregated = SummaryService.aggregate_opinions(task)

        opinion_ids = aggregated['opinion_ids']
        if not opinion_ids:
            raise ValueError(f'任务 {task.task_id} 无已提交的审稿意见，无法生成汇总报告')

        dimension_comparison = aggregated['dimension_comparison']
        recommendation_distribution = aggregated['recommendation_distribution']
        revision_suggestions_summary = aggregated['revision_suggestions_summary']
        overall_comments = aggregated['overall_comments']

        # 2. 分歧标注
        conflict_points = SummaryService.detect_conflicts(dimension_comparison)

        # 3. 一致点分析
        consensus_points = SummaryService.analyze_consensus(dimension_comparison)

        # 4. 规则引擎匹配
        reviewer_count = recommendation_distribution['total']
        rule_result = SummaryService.match_rule(recommendation_distribution, reviewer_count)

        # 构建系统终审建议（S-07精简：仅输出推荐分布+规则匹配结果，不生成自然语言建议语）
        system_recommendation = {
            'distribution': recommendation_distribution,
            'matchedRuleId': rule_result['matchedRuleId'],
            'conclusion': rule_result['conclusion'],
            'advisoryOnly': rule_result.get('advisoryOnly', False),
        }

        # 5. 保存汇总报告（如已存在则更新）
        report = None
        try:
            report = SummaryReport.objects.get(task=task)
            logger.info('任务 %s 的汇总报告已存在(%s)，将更新', task.task_id, report.report_id)
        except SummaryReport.DoesNotExist:
            pass

        if report is None:
            report = SummaryReport(task=task)

        report.opinion_ids = opinion_ids
        report.dimension_comparison = dimension_comparison
        report.recommendation_distribution = recommendation_distribution
        report.conflict_points = conflict_points
        report.consensus_points = consensus_points
        report.revision_suggestions_summary = revision_suggestions_summary
        report.overall_comments = overall_comments
        report.system_recommendation = system_recommendation
        report.editor_decision = {}
        report.round = 1
        report.save()

        # 6. 状态转换：SUBMITTED -> SUMMARIZED
        task = StateMachineService.execute_transition(
            task, 'SUMMARIZED', operator_user,
            '编辑触发汇总报告生成'
        )

        # 7. 通知编辑部
        try:
            NotificationService.send_summarize(report)
        except Exception as e:
            logger.error('发送汇总通知失败: %s', str(e))

        logger.info(
            '汇总报告已生成: task=%s, report=%s, rule=%s, conclusion=%s',
            task.task_id, report.report_id,
            rule_result['matchedRuleId'], rule_result['conclusion'],
        )

        return report
