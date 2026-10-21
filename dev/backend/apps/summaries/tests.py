"""汇总规则引擎测试 - 对应 AC-S-07（7条规则优先级匹配）与 N-01（Rule-4 重定义）"""
from datetime import date

from django.test import TestCase

from apps.forms.models import ReviewForm, ReviewOpinion
from apps.summaries.services import SummaryService
from apps.tasks.models import ReviewTask, ReviewAssignment, Template, StateLog
from apps.users.models import User


def dist(accept=0, minor=0, major=0, reject=0):
    return {
        'ACCEPT': accept, 'MINOR_REVISION': minor,
        'MAJOR_REVISION': major, 'REJECT': reject,
        'total': accept + minor + major + reject,
    }


class MatchRuleTests(TestCase):
    """规则引擎匹配 - 每条规则的触发条件与优先级"""

    def test_rule_1_unanimous_accept(self):
        """Rule-1: 全票接收 -> 建议接收"""
        r = SummaryService.match_rule(dist(accept=3), 3)
        self.assertEqual(r['matchedRuleId'], 'Rule-1')
        self.assertEqual(r['conclusion'], '建议接收')
        self.assertFalse(r['advisoryOnly'])

    def test_rule_2_majority_accept_or_minor(self):
        """Rule-2: 多数接收/小修（非全票）-> 倾向接收"""
        r = SummaryService.match_rule(dist(accept=2, minor=1), 3)
        self.assertEqual(r['matchedRuleId'], 'Rule-2')

    def test_rule_3_majority_accept_with_dissent(self):
        """Rule-3: 多数接收/小修 + 有大修或拒稿（但未构成三分散）-> 倾向接收但需讨论

        注意：accept+minor+major 三者并存且无拒稿时，按 N-01 重定义优先命中
        Rule-4 条件B（技术实施方案 §3.3 验证表），故此处用 minor 占多数的分布。
        """
        r = SummaryService.match_rule(dist(minor=2, major=1), 3)
        self.assertEqual(r['matchedRuleId'], 'Rule-3')
        self.assertEqual(r['conclusion'], '倾向接收但需讨论')

        # 交叉验证：三分散（接收+小修+大修、无拒稿）按 N-01 命中 Rule-4 条件B
        r2 = SummaryService.match_rule(dist(accept=1, minor=1, major=1), 3)
        self.assertEqual(r2['matchedRuleId'], 'Rule-4')

    def test_rule_4_condition_a(self):
        """Rule-4 条件A（N-01重定义）: 小修+大修+拒稿分散，无接收，无多数 -> 分歧需讨论"""
        r = SummaryService.match_rule(dist(minor=2, major=2, reject=1), 5)
        self.assertEqual(r['matchedRuleId'], 'Rule-4')
        self.assertEqual(r['conclusion'], '分歧需讨论')

    def test_rule_4_condition_b(self):
        """Rule-4 条件B（N-01重定义）: 接收+小修+大修分散，无拒稿，无多数 -> 分歧需讨论"""
        r = SummaryService.match_rule(dist(accept=1, minor=2, major=2), 5)
        self.assertEqual(r['matchedRuleId'], 'Rule-4')

    def test_rule_5_majority_major(self):
        """Rule-5: 多数大修 -> 建议大修"""
        r = SummaryService.match_rule(dist(major=2, minor=1), 3)
        self.assertEqual(r['matchedRuleId'], 'Rule-5')
        self.assertEqual(r['conclusion'], '建议大修')

    def test_rule_6_majority_reject(self):
        """Rule-6: 多数拒稿 -> 建议拒稿"""
        r = SummaryService.match_rule(dist(reject=2, minor=1), 3)
        self.assertEqual(r['matchedRuleId'], 'Rule-6')
        self.assertEqual(r['conclusion'], '建议拒稿')

    def test_rule_7_accept_and_reject_coexist(self):
        """Rule-7（最高优先级）: 接收与拒稿并存 -> 严重分歧需讨论"""
        r = SummaryService.match_rule(dist(accept=1, reject=1, minor=1), 3)
        self.assertEqual(r['matchedRuleId'], 'Rule-7')
        self.assertEqual(r['conclusion'], '严重分歧需讨论')

    def test_priority_rule7_over_rule6(self):
        """优先级：接收+拒稿并存 优先于 多数拒稿"""
        # reject=2 已构成多数（majority=2），但 Rule-7 优先
        r = SummaryService.match_rule(dist(accept=1, reject=2), 3)
        self.assertEqual(r['matchedRuleId'], 'Rule-7')

    def test_priority_rule4_over_rule6(self):
        """优先级：三分散无多数（Rule-4）优先于拒稿多数（Rule-6）

        反例校验：reject 构成多数时条件A不成立，应落到 Rule-6
        """
        r = SummaryService.match_rule(dist(minor=1, major=1, reject=2), 4)
        self.assertEqual(r['matchedRuleId'], 'Rule-6')

    def test_advisory_annotation_for_small_panel(self):
        """1-2位审稿人时结论追加「仅供参考，建议人工判断」"""
        r = SummaryService.match_rule(dist(accept=1, minor=1), 2)
        self.assertTrue(r['advisoryOnly'])
        self.assertIn('仅供参考', r['conclusion'])

        r3 = SummaryService.match_rule(dist(accept=2, minor=1), 3)
        self.assertFalse(r3['advisoryOnly'])
        self.assertNotIn('仅供参考', r3['conclusion'])

    def test_empty_distribution(self):
        """无意见时返回无规则匹配"""
        r = SummaryService.match_rule(dist(), 0)
        self.assertIsNone(r['matchedRuleId'])

    def test_rule_0_unreachable_exhaustive(self):
        """穷举性质测试：1~7位审稿人的全部推荐分布都能命中 Rule-1~7，不落入 Rule-0"""
        from itertools import product
        for total in range(1, 8):
            # 枚举 total 拆分为 (accept, minor, major, reject) 的全部组合
            for a in range(total + 1):
                for mn in range(total - a + 1):
                    for mj in range(total - a - mn + 1):
                        rj = total - a - mn - mj
                        r = SummaryService.match_rule(dist(a, mn, mj, rj), total)
                        self.assertNotEqual(
                            r['matchedRuleId'], 'Rule-0',
                            msg=f'未覆盖分布: accept={a} minor={mn} major={mj} reject={rj}',
                        )


class ConflictAndConsensusTests(TestCase):
    """分歧标注（红/黄）与一致点分析（正向/负向）"""

    @staticmethod
    def _dim(dim_id, scores):
        return {
            'dimensionId': dim_id,
            'dimensionName': f'维度{dim_id}',
            'scores': [
                {'reviewerId': f'U-{i}', 'reviewerName': f'审稿人{i}',
                 'opinionId': f'RO-{i}', 'score': s, 'comment': ''}
                for i, s in enumerate(scores)
            ],
        }

    def test_detect_conflicts_levels(self):
        dims = [
            self._dim('D1', [5, 2]),   # diff=3 -> 严重(红)
            self._dim('D2', [4, 2]),   # diff=2 -> 明显(黄)
            self._dim('D3', [4, 3]),   # diff=1 -> 一致，不列入
            self._dim('D4', [4]),      # 仅1个有效评分，跳过
        ]
        conflicts = SummaryService.detect_conflicts(dims)
        self.assertEqual(len(conflicts), 2)
        self.assertEqual(conflicts[0]['dimensionId'], 'D1')
        self.assertEqual(conflicts[0]['level'], 'SEVERE')
        self.assertEqual(conflicts[0]['color'], 'red')
        self.assertEqual(conflicts[0]['distributionText'], '1/2位评分5分，1/2位评分2分')
        self.assertEqual(conflicts[1]['dimensionId'], 'D2')
        self.assertEqual(conflicts[1]['level'], 'MODERATE')
        self.assertEqual(conflicts[1]['color'], 'yellow')

    def test_analyze_consensus(self):
        dims = [
            self._dim('D1', [5, 4]),   # avg=4.5 -> 正向一致
            self._dim('D2', [1, 2]),   # avg=1.5 -> 负向一致
            self._dim('D3', [3, 3]),   # avg=3 -> 中间分，跳过
            self._dim('D4', [5, 1]),   # diff=4 -> 分歧，不属于一致点
        ]
        consensus = SummaryService.analyze_consensus(dims)
        self.assertEqual(len(consensus), 2)
        self.assertEqual(consensus[0]['type'], 'POSITIVE')
        self.assertEqual(consensus[0]['avgScore'], 4.5)
        self.assertEqual(consensus[1]['type'], 'NEGATIVE')
        self.assertEqual(consensus[1]['avgScore'], 1.5)


class GenerateReportTests(TestCase):
    """汇总报告生成集成测试：聚合 -> 分歧 -> 规则 -> 状态转换 SUBMITTED -> SUMMARIZED"""

    def setUp(self):
        self.editor = User.objects.create(
            email='editor@test.local', name='编辑部', roles=['EDITOR'],
        )
        self.editor.set_password('pass12345')
        self.editor.save()

        self.author = User.objects.create(
            email='author@test.local', name='作者', roles=['AUTHOR'],
        )
        self.template = Template.objects.create(
            template_name='测试模板', template_type='SYSTEM_DEFAULT',
            dimensions=[
                {'dimensionId': 'D1', 'dimensionName': '研究意义'},
                {'dimensionId': 'D2', 'dimensionName': '创新性'},
            ],
        )
        self.task = ReviewTask.objects.create(
            title='测试稿件', abstract='摘要', keywords=['气候'],
            subject_area='经济学', manuscript_type='论文',
            manuscript_file='test.pdf', review_mode='SINGLE_BLIND',
            deadline=date(2026, 12, 31), template_id=self.template.template_id,
            author_user_id=self.author, status='SUBMITTED',
        )
        self.form = ReviewForm.objects.create(
            task=self.task, template=self.template,
            template_snapshot={}, dimensions=self.template.dimensions,
        )
        self.reviewers = []
        for i, recommendation in enumerate(['ACCEPT', 'REJECT', 'MINOR_REVISION']):
            reviewer = User.objects.create(
                email=f'reviewer{i}@test.local', name=f'审稿人{i}', roles=['REVIEWER'],
            )
            self.reviewers.append(reviewer)
            assignment = ReviewAssignment.objects.create(
                task=self.task, reviewer=reviewer,
                deadline=date(2026, 12, 31),
                invitation_expiry=date(2026, 12, 31),
                assignment_status='SUBMITTED',
                assigned_by=self.editor,
            )
            ReviewOpinion.objects.create(
                task=self.task, form=self.form, assignment=assignment,
                reviewer=reviewer,
                dimension_scores=[
                    {'dimensionId': 'D1', 'score': 5 if i == 0 else (1 if i == 1 else 4), 'comment': 'x' * 50},
                    {'dimensionId': 'D2', 'score': 4 if i == 0 else (2 if i == 1 else 3), 'comment': 'y' * 50},
                ],
                recommendation=recommendation,
                overall_comment='z' * 100,
                revision_suggestions=['建议一', '建议二'],
                status='SUBMITTED', round=1,
            )

    def test_generate_report_full_flow(self):
        report = SummaryService.generate_report(self.task, operator_user=self.editor)

        # 聚合：3份意见
        self.assertEqual(len(report.opinion_ids), 3)
        self.assertEqual(report.recommendation_distribution['total'], 3)
        self.assertEqual(report.recommendation_distribution['ACCEPT'], 1)
        self.assertEqual(report.recommendation_distribution['REJECT'], 1)

        # 维度对齐：2个维度 x 3位审稿人
        self.assertEqual(len(report.dimension_comparison), 2)
        self.assertEqual(len(report.dimension_comparison[0]['scores']), 3)

        # 规则引擎：ACCEPT 与 REJECT 并存 -> Rule-7
        self.assertEqual(report.system_recommendation['matchedRuleId'], 'Rule-7')

        # 分歧标注：D1 [5,1,4] diff=4 严重；D2 [4,2,3] diff=2 明显
        conflict_dims = {c['dimensionId']: c for c in report.conflict_points}
        self.assertEqual(conflict_dims['D1']['level'], 'SEVERE')
        self.assertEqual(conflict_dims['D2']['level'], 'MODERATE')

        # 状态转换：SUBMITTED -> SUMMARIZED，且留有状态日志
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'SUMMARIZED')
        log = StateLog.objects.filter(
            task=self.task, from_state='SUBMITTED', to_state='SUMMARIZED',
        ).count()
        self.assertEqual(log, 1)

        # 通知编辑部（send_summarize）
        from apps.notifications.models import Notification
        notified = Notification.objects.filter(
            task=self.task, type=Notification.Type.SUMMARIZE,
        ).count()
        self.assertGreaterEqual(notified, 1)

    def test_generate_report_rejects_wrong_state(self):
        self.task.status = 'REVIEWING'
        self.task.save()
        from apps.tasks.state_machine import StateMachineError
        with self.assertRaises(StateMachineError):
            SummaryService.generate_report(self.task)
