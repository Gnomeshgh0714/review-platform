"""P0修复回归测试 - 知识库第一阶段匿名化（对应评审意见 V1.1 致命#8）

修复前：_build_anonymized_dimensions 只过滤 top-level underscore 键
（reviewer_name/reviewer_id），而汇总报告实际以 camelCase
（reviewerId/reviewerName）嵌在 scores/overall_comments 内，
导致审稿人真实姓名与用户编号原样写入 anonymized_dimensions；
summary 渲染还因键名错位输出"未知维度/均值=0"。
"""
from datetime import date, timedelta

from django.test import TestCase

from apps.knowledge.models import KnowledgeItem
from apps.knowledge.services import AnonymizationService
from apps.summaries.models import SummaryReport
from apps.tasks.models import ReviewTask, Template
from apps.users.models import User


REVIEWER_NAME = '欧阳清华'
REVIEWER_EMAIL = 'reviewer@test.local'


def make_task(author):
    template = Template.objects.create(
        template_name='测试模板', template_type='SYSTEM_DEFAULT',
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义'},
            {'dimensionId': 'D2', 'dimensionName': '创新性'},
        ],
    )
    return ReviewTask.objects.create(
        title='匿名化测试稿件', abstract='摘要',
        keywords=['气候', '模型', '预测'],
        subject_area='环境科学', manuscript_type='论文',
        manuscript_file='anon-test.pdf', review_mode='DOUBLE_BLIND',
        deadline=date.today() + timedelta(days=14),
        template_id=template.template_id, author_user_id=author,
        status='DECIDED', final_decision='MINOR_REVISION',
    )


def make_report(task, reviewer):
    """按 SummaryService.aggregate_opinions 的真实键名构造报告"""
    return SummaryReport.objects.create(
        task=task,
        opinion_ids=['RO-20261016-0001'],
        dimension_comparison=[
            {
                'dimensionId': 'D1', 'dimensionName': '研究意义',
                'scores': [
                    {'reviewerId': reviewer.user_id, 'reviewerName': REVIEWER_NAME,
                     'opinionId': 'RO-20261016-0001', 'score': 4, 'comment': '问题重要'},
                    {'reviewerId': 'U-20261016-9999', 'reviewerName': '第二审稿人',
                     'opinionId': 'RO-20261016-0002', 'score': 5, 'comment': '视角新颖'},
                ],
            },
            {
                'dimensionId': 'D2', 'dimensionName': '创新性',
                'scores': [
                    {'reviewerId': reviewer.user_id, 'reviewerName': REVIEWER_NAME,
                     'opinionId': 'RO-20261016-0001', 'score': 3, 'comment': '方法常规'},
                ],
            },
        ],
        recommendation_distribution={'ACCEPT': 1, 'MINOR_REVISION': 1, 'total': 2},
        conflict_points=[{
            'dimensionId': 'D2', 'dimensionName': '创新性',
            'level': 'MODERATE', 'levelLabel': '明显', 'color': 'yellow',
            'maxScore': 5, 'minScore': 3, 'diff': 2,
            'scoreDistribution': {'5': 1, '3': 1},
            'distributionText': '1/2位评分5分，1/2位评分3分',
        }],
        consensus_points=[{
            'dimensionId': 'D1', 'dimensionName': '研究意义',
            'type': 'POSITIVE', 'avg': 4.5, 'description': '两位审稿人均认可研究意义',
        }],
        revision_suggestions_summary={
            'by_dimension': {'D2': [{
                'reviewerName': REVIEWER_NAME,
                'reviewerId': reviewer.user_id,
                'suggestion': '建议补充稳健性检验',
            }]},
            'all': [],
        },
        overall_comments=[{
            'reviewerId': reviewer.user_id, 'reviewerName': REVIEWER_NAME,
            'opinionId': 'RO-20261016-0001',
            'recommendation': 'MINOR_REVISION', 'recommendationDisplay': '小修',
            'comment': '整体扎实，建议补充稳健性检验',
        }],
        system_recommendation={
            'matchedRuleId': 'Rule-2', 'conclusion': '倾向接收', 'advisoryOnly': False,
        },
    )


def walk_identity_keys(value):
    """递归收集出现过的身份键名"""
    found = set()
    if isinstance(value, dict):
        for k, v in value.items():
            if k in AnonymizationService.IDENTITY_KEYS:
                found.add(k)
            found |= walk_identity_keys(v)
    elif isinstance(value, list):
        for item in value:
            found |= walk_identity_keys(item)
    return found


class StripIdentityKeysTests(TestCase):
    """递归脱敏单元测试：camelCase/underscore 双口径、任意嵌套层级"""

    def test_strips_camelcase_keys_nested(self):
        data = {
            'dimensionName': '研究意义',
            'scores': [{'reviewerId': 'U-1', 'reviewerName': '张三',
                        'reviewerEmail': 'z@t.local', 'score': 4}],
        }
        cleaned = AnonymizationService._strip_identity_keys(data)
        self.assertEqual(walk_identity_keys(cleaned), set())
        self.assertEqual(cleaned['scores'][0]['score'], 4)  # 业务数据保留

    def test_strips_underscore_keys(self):
        data = {'reviewer_name': '张三', 'reviewer_id': 'U-1', 'other': [{'reviewer_email': 'z@t.local'}]}
        cleaned = AnonymizationService._strip_identity_keys(data)
        self.assertEqual(walk_identity_keys(cleaned), set())
        self.assertEqual(cleaned['other'], [{}])  # 键被移除，容器结构保留

    def test_strips_from_lists_of_dicts(self):
        data = [{'reviewerName': '甲'}, 'plain string', {'nested': {'reviewerId': 'U-9'}}]
        cleaned = AnonymizationService._strip_identity_keys(data)
        self.assertEqual(walk_identity_keys(cleaned), set())
        self.assertEqual(cleaned[1], 'plain string')

    def test_plain_scalars_untouched(self):
        self.assertEqual(AnonymizationService._strip_identity_keys(42), 42)
        self.assertEqual(AnonymizationService._strip_identity_keys('文本'), '文本')
        self.assertIsNone(AnonymizationService._strip_identity_keys(None))


class AutoAnonymizeTests(TestCase):

    def setUp(self):
        self.author = User.objects.create(
            email='author@test.local', name='作者甲', roles=['AUTHOR'])
        self.reviewer = User.objects.create(
            email=REVIEWER_EMAIL, name=REVIEWER_NAME, roles=['REVIEWER'])
        self.task = make_task(self.author)
        self.report = make_report(self.task, self.reviewer)

    def test_anonymized_dimensions_contain_no_identity(self):
        """致命#8：审稿人姓名/编号不得进入 anonymized_dimensions"""
        item = AnonymizationService.auto_anonymize(self.task, self.report)
        self.assertIsInstance(item, KnowledgeItem)

        self.assertEqual(
            walk_identity_keys(item.anonymized_dimensions), set(),
            f'仍残留身份键: {walk_identity_keys(item.anonymized_dimensions)}',
        )
        # 原始报告不受影响（编辑部数据保留）
        self.report.refresh_from_db()
        self.assertIn(REVIEWER_NAME,
                      str(self.report.dimension_comparison))

    def test_anonymized_dimensions_keep_business_data(self):
        item = AnonymizationService.auto_anonymize(self.task, self.report)
        dims = {d['dimensionId']: d for d in item.anonymized_dimensions}
        self.assertEqual(dims['D1']['dimensionName'], '研究意义')
        scores = dims['D1']['scores']
        self.assertEqual(len(scores), 2)
        self.assertEqual({s['score'] for s in scores}, {4, 5})
        self.assertTrue(all('comment' in s for s in scores))

    def test_anonymized_summary_has_no_identity_and_renders_dimensions(self):
        """键名对齐：维度名与均值正确渲染，不再是"未知维度/均值=0" """
        item = AnonymizationService.auto_anonymize(self.task, self.report)
        summary = item.anonymized_summary

        self.assertNotIn(REVIEWER_NAME, summary)
        self.assertNotIn(REVIEWER_EMAIL, summary)
        self.assertNotIn(self.reviewer.user_id, summary)

        self.assertIn('研究意义', summary)
        self.assertIn('创新性', summary)
        self.assertNotIn('未知维度', summary)
        # D1 均值 = (4+5)/2 = 4.5
        self.assertIn('均值=4.5', summary)

    def test_summary_renders_conflict_consensus_and_comments(self):
        item = AnonymizationService.auto_anonymize(self.task, self.report)
        summary = item.anonymized_summary
        self.assertIn('分歧点', summary)
        self.assertIn('1/2位评分5分，1/2位评分3分', summary)
        self.assertIn('一致点', summary)
        # 综合评语按"审稿人A"口径，不带姓名
        self.assertIn('审稿人A: 整体扎实', summary)

    def test_duplicate_archive_rejected(self):
        AnonymizationService.auto_anonymize(self.task, self.report)
        with self.assertRaises(ValueError):
            AnonymizationService.auto_anonymize(self.task, self.report)

    def test_auto_anonymize_without_report(self):
        """report=None：仍归档基础数据，不报错"""
        task2 = make_task(self.author)
        item = AnonymizationService.auto_anonymize(task2, None)
        self.assertEqual(item.anonymized_dimensions, [])
        self.assertIn('环境科学', item.anonymized_summary)
