"""#017 测试补课 —— 知识库端点 API 测试（决策 #014 提请的测试补课挂账项）

覆盖 apps/knowledge 五个端点的权限（编辑部 vs 审稿人 vs 作者）与行为断言：
- GET  /api/knowledge/search/             检索（审稿人+编辑部；纯作者 403；仅 APPROVED 入结果）
- GET  /api/knowledge/<id>/detail/        详情（#018 修复1：DRF 3.18.3 保留字
                                          detail 冲突已修——action 改名
                                          item_detail 而 URL 不变；行为断言见
                                          KnowledgeDetailApiTests，服务层口径
                                          见 KnowledgeGetDetailServiceTests）
- GET  /api/knowledge/pending_reviews/    待审核列表（仅编辑部）
- POST /api/knowledge/<id>/review/        审核匿名化（仅编辑部；review_notes 真实落库，P2 严重#5）
- GET  /api/knowledge/export/             导出（仅编辑部；不含 source_task_id）

既有行为锁定（断言现状，非缺陷判定）：
- 检索 score_range 目前仅实现 high/mid_high 两档（anonymized_dimensions 的
  contains 简化匹配 [{'avg': N}]），传 mid/low 为无过滤 no-op——与
  high/mid_high 的行为不对称。若后续补实现，需同步更新本文件断言。
- review 端点对不存在的 knowledge_id 返回 400（ValueError 映射 400，非 404）。
"""
from datetime import date, timedelta

from rest_framework.test import APIClient

from django.test import TestCase

from apps.knowledge.models import KnowledgeItem, AccessLog
from apps.tasks.models import ReviewTask, Template
from apps.users.models import User


def make_user(email, roles, name):
    return User.objects.create(email=email, name=name, roles=roles)


def make_task(author, status='PENDING', **kwargs):
    template = Template.objects.create(
        template_name='知识库测试模板', template_type='SYSTEM_DEFAULT',
        dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
    )
    defaults = dict(
        title='知识库测试稿件', abstract='摘要', keywords=['a', 'b', 'c'],
        subject_area='经济学', manuscript_type='论文',
        manuscript_file='kb-test.pdf', review_mode='SINGLE_BLIND',
        deadline=date.today() + timedelta(days=14),
        template_id=template.template_id, author_user_id=author, status=status,
    )
    defaults.update(kwargs)
    return ReviewTask.objects.create(**defaults)


def make_knowledge_item(source_task_id, status='APPROVED', **kwargs):
    """构造一条知识库条目（字段口径与 AnonymizationService.auto_anonymize 对齐）"""
    defaults = dict(
        source_task_id=source_task_id,
        subject_area='经济学',
        manuscript_type='论文',
        keywords=['a', 'b', 'c'],
        review_year=2026,
        review_month=10,
        review_mode='SINGLE_BLIND',
        anonymized_dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
        anonymized_recommendations={'ACCEPT': 1, 'total': 1},
        anonymized_summary='【稿件信息】学科: 经济学，关键词: a, b, c',
        template_info={'source_template_id': 'TPL-X'},
        final_decision='ACCEPT',
        tags=['经济学'],
        anonymization_status=status,
        pending_review_segments=[],
    )
    defaults.update(kwargs)
    return KnowledgeItem.objects.create(**defaults)


class KnowledgeSearchPermissionTests(TestCase):
    """检索端点角色门：审稿人/编辑部放行，纯作者拒绝"""

    def setUp(self):
        self.editor = make_user('kb-editor@test.local', ['EDITOR'], '编辑部')
        self.reviewer = make_user('kb-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.author = make_user('kb-author@test.local', ['AUTHOR'], '作者')
        self.reviewer_author = make_user(
            'kb-ra@test.local', ['REVIEWER', 'AUTHOR'], '审稿人兼作者')
        self.client = APIClient()

    def test_reviewer_can_search(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get('/api/knowledge/search/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('count', resp.data)
        self.assertIn('is_cold_start', resp.data)

    def test_editor_can_search(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get('/api/knowledge/search/')
        self.assertEqual(resp.status_code, 200)

    def test_pure_author_forbidden(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.get('/api/knowledge/search/')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('作者无权访问', str(resp.data))

    def test_dual_role_reviewer_author_allowed(self):
        """审稿人兼作者按审稿人口径放行"""
        self.client.force_authenticate(user=self.reviewer_author)
        resp = self.client.get('/api/knowledge/search/')
        self.assertEqual(resp.status_code, 200)


class KnowledgeSearchBehaviorTests(TestCase):
    """检索端点行为：状态过滤 / 关键词 / 学科 / 冷启动 / score_range 既有两档"""

    def setUp(self):
        self.editor = make_user('kb-editor@test.local', ['EDITOR'], '编辑部')
        self.reviewer = make_user('kb-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.client = APIClient()
        self.client.force_authenticate(user=self.reviewer)

    def test_only_approved_items_in_results(self):
        """PENDING_REVIEW / REJECTED / PERMANENTLY_EXCLUDED 均不入检索结果"""
        make_knowledge_item(
            'RT-SEARCH-01', status='APPROVED', keywords=['已过审'])
        make_knowledge_item(
            'RT-SEARCH-02', status='PENDING_REVIEW', keywords=['待审核'])
        make_knowledge_item(
            'RT-SEARCH-03', status='REJECTED', keywords=['已退回'])
        make_knowledge_item(
            'RT-SEARCH-04', status='PERMANENTLY_EXCLUDED', keywords=['永久排除'])

        resp = self.client.get('/api/knowledge/search/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['keywords'], ['已过审'])

        # 未过审条目按各自关键词检索均不可见（关键词入 keywords 字段）
        for kw in ('待审核', '已退回', '永久排除'):
            resp2 = self.client.get(
                '/api/knowledge/search/', {'keyword': kw})
            self.assertEqual(
                resp2.data['count'], 0,
                f'非 APPROVED 条目（{kw}）不应出现在检索结果中',
            )

    def test_keyword_hits_anonymized_summary(self):
        make_knowledge_item(
            'RT-KW-01', anonymized_summary='本文聚焦城乡收入差距的演化路径')
        make_knowledge_item(
            'RT-KW-02', anonymized_summary='本文研究货币政策传导机制')

        resp = self.client.get('/api/knowledge/search/', {'keyword': '货币政策'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)

    def test_subject_area_exact_filter(self):
        make_knowledge_item('RT-SUBJ-01', subject_area='经济学')
        make_knowledge_item('RT-SUBJ-02', subject_area='环境科学')

        resp = self.client.get(
            '/api/knowledge/search/', {'subject_area': '环境科学'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['subject_area'], '环境科学')

    def test_cold_start_guide_returned_when_empty(self):
        """空结果冷启动：is_cold_start=True 且带模板评分指引"""
        resp = self.client.get('/api/knowledge/search/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 0)
        self.assertEqual(resp.data['total_pages'], 0)
        self.assertTrue(resp.data['is_cold_start'])
        guide = resp.data['cold_start_guide']
        self.assertIsNotNone(guide)
        self.assertIn('dimensions', guide)
        self.assertEqual(len(guide['dimensions']), 4)

    def test_search_writes_access_log(self):
        make_knowledge_item('RT-LOG-01')
        resp = self.client.get('/api/knowledge/search/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            AccessLog.objects.filter(
                user=self.reviewer, action='SEARCH_KB', target_id='',
            ).exists()
        )

    def test_score_range_high_filters_by_contains_avg4(self):
        """既有行为：high 档 = anonymized_dimensions contains [{'avg': 4}]"""
        make_knowledge_item(
            'RT-SCORE-H', anonymized_dimensions=[{'avg': 4}],
            keywords=['高分组'])
        make_knowledge_item(
            'RT-SCORE-MH', anonymized_dimensions=[{'avg': 3}],
            keywords=['中高分'])
        make_knowledge_item(
            'RT-SCORE-P', anonymized_dimensions=[{'dimensionId': 'D1'}],
            keywords=['普通组'])

        resp = self.client.get('/api/knowledge/search/', {'score_range': 'high'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['keywords'], ['高分组'])

    def test_score_range_mid_high_filters_by_contains_avg3(self):
        make_knowledge_item(
            'RT-SCORE-H2', anonymized_dimensions=[{'avg': 4}],
            keywords=['高分组'])
        make_knowledge_item(
            'RT-SCORE-MH2', anonymized_dimensions=[{'avg': 3}],
            keywords=['中高分组'])

        resp = self.client.get(
            '/api/knowledge/search/', {'score_range': 'mid_high'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['keywords'], ['中高分组'])

    def test_score_range_mid_and_low_are_noop(self):
        """既有行为：mid/low 未实现过滤逻辑，传参后返回全部 APPROVED 条目"""
        make_knowledge_item(
            'RT-NM-01', anonymized_dimensions=[{'avg': 4}], keywords=['甲'])
        make_knowledge_item(
            'RT-NM-02', anonymized_dimensions=[{'avg': 3}], keywords=['乙'])
        make_knowledge_item(
            'RT-NM-03', anonymized_dimensions=[{'dimensionId': 'D1'}],
            keywords=['丙'])

        for param in ('mid', 'low'):
            resp = self.client.get(
                '/api/knowledge/search/', {'score_range': param})
            self.assertEqual(resp.status_code, 200, f'score_range={param}')
            self.assertEqual(
                resp.data['count'], 3,
                f'score_range={param} 现状为无过滤 no-op，应返回全部 3 条',
            )


class KnowledgeDetailApiTests(TestCase):
    """#018 修复1：detail 端点正常行为断言（替换原 500 现状锁定测试）

    原因：原方法名 detail 与 DRF 3.18.3 ViewSetMixin.as_view() 的保留
    initkwarg 冲突（URLconf 加载时 cls.detail = None 覆盖方法），
    GET /api/knowledge/<id>/detail/ 必 500；#018 将 action 改名
    item_detail（url_path 不变 → 对外 URL 不变）后，端点行为对齐
    KnowledgeGetDetailServiceTests 已钉死的服务层口径：
    审稿人仅 APPROVED、编辑部任意状态、404 隐藏存在性、纯作者 403。
    """

    def setUp(self):
        self.editor = make_user('kb-editor@test.local', ['EDITOR'], '编辑部')
        self.reviewer = make_user('kb-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.author = make_user('kb-author@test.local', ['AUTHOR'], '作者')
        self.client = APIClient()

    def test_editor_reads_approved_detail(self):
        item = make_knowledge_item('RT-DET-10', status='APPROVED')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get(f'/api/knowledge/{item.knowledge_id}/detail/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['knowledge_id'], item.knowledge_id)
        self.assertEqual(resp.data['anonymization_status'], 'APPROVED')

    def test_reviewer_reads_approved_detail_and_writes_access_log(self):
        """审稿人查 APPROVED 详情：200 且落 VIEW_KB_ITEM 访问日志"""
        item = make_knowledge_item('RT-DET-11', status='APPROVED')
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get(f'/api/knowledge/{item.knowledge_id}/detail/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['knowledge_id'], item.knowledge_id)
        self.assertTrue(
            AccessLog.objects.filter(
                user=self.reviewer, action='VIEW_KB_ITEM',
                target_id=item.knowledge_id,
            ).exists()
        )

    def test_editor_reads_non_approved_detail(self):
        """编辑部可查任意状态（待审核条目详情 200）"""
        item = make_knowledge_item('RT-DET-12', status='PENDING_REVIEW')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get(f'/api/knowledge/{item.knowledge_id}/detail/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['anonymization_status'], 'PENDING_REVIEW')

    def test_reviewer_cannot_read_non_approved_hidden_as_404(self):
        """非 APPROVED 对审稿人 404 隐藏存在性（服务层 ValueError → 端点 404）"""
        item = make_knowledge_item('RT-DET-13', status='PENDING_REVIEW')
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get(f'/api/knowledge/{item.knowledge_id}/detail/')
        self.assertEqual(resp.status_code, 404)

    def test_pure_author_forbidden(self):
        item = make_knowledge_item('RT-DET-14', status='APPROVED')
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(f'/api/knowledge/{item.knowledge_id}/detail/')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('作者无权', str(resp.data))

    def test_missing_item_returns_404(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get('/api/knowledge/KI-20990101-9999/detail/')
        self.assertEqual(resp.status_code, 404)


class KnowledgeGetDetailServiceTests(TestCase):
    """详情行为口径钉死（服务层，端点修复后直接生效）：
    审稿人仅可见 APPROVED；编辑部任意状态；记录 VIEW_KB_ITEM 日志
    """

    def setUp(self):
        self.editor = make_user('kb-editor@test.local', ['EDITOR'], '编辑部')
        self.reviewer = make_user('kb-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.client = APIClient()

    def test_reviewer_reads_approved_detail(self):
        from apps.knowledge.services import KnowledgeService
        item = make_knowledge_item('RT-DET-01', status='APPROVED')
        data = KnowledgeService.get_detail(item.knowledge_id, self.reviewer)
        self.assertEqual(data['knowledge_id'], item.knowledge_id)
        self.assertEqual(data['anonymization_status'], 'APPROVED')
        self.assertTrue(
            AccessLog.objects.filter(
                user=self.reviewer, action='VIEW_KB_ITEM',
                target_id=item.knowledge_id,
            ).exists()
        )

    def test_reviewer_cannot_read_non_approved(self):
        """未过审条目对审稿人抛 ValueError（端点层映射 404 隐藏存在性）"""
        from apps.knowledge.services import KnowledgeService
        item = make_knowledge_item('RT-DET-02', status='PENDING_REVIEW')
        with self.assertRaises(ValueError):
            KnowledgeService.get_detail(item.knowledge_id, self.reviewer)

    def test_editor_reads_pending_review_detail(self):
        from apps.knowledge.services import KnowledgeService
        item = make_knowledge_item('RT-DET-03', status='PENDING_REVIEW')
        data = KnowledgeService.get_detail(item.knowledge_id, self.editor)
        self.assertEqual(data['anonymization_status'], 'PENDING_REVIEW')

    def test_missing_item_raises_value_error(self):
        from apps.knowledge.services import KnowledgeService
        with self.assertRaises(ValueError):
            KnowledgeService.get_detail('KI-20990101-9999', self.reviewer)


class KnowledgePendingReviewsApiTests(TestCase):
    """待审核列表：仅编辑部；只含 PENDING_REVIEW 与 REJECTED"""

    def setUp(self):
        self.editor = make_user('kb-editor@test.local', ['EDITOR'], '编辑部')
        self.reviewer = make_user('kb-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.author = make_user('kb-author@test.local', ['AUTHOR'], '作者')
        self.client = APIClient()

    def test_editor_sees_pending_and_rejected_only(self):
        make_knowledge_item('RT-PR-01', status='PENDING_REVIEW')
        make_knowledge_item('RT-PR-02', status='REJECTED')
        make_knowledge_item('RT-PR-03', status='APPROVED')
        make_knowledge_item('RT-PR-04', status='PERMANENTLY_EXCLUDED')

        self.client.force_authenticate(user=self.editor)
        resp = self.client.get('/api/knowledge/pending_reviews/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 2)
        statuses = {r['anonymization_status'] for r in resp.data['results']}
        self.assertEqual(statuses, {'PENDING_REVIEW', 'REJECTED'})

    def test_reviewer_forbidden(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get('/api/knowledge/pending_reviews/')
        self.assertEqual(resp.status_code, 403)

    def test_author_forbidden(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.get('/api/knowledge/pending_reviews/')
        self.assertEqual(resp.status_code, 403)


class KnowledgeReviewAnonymizationApiTests(TestCase):
    """审核端点：仅编辑部；review_notes 落库（P2 严重#5）；状态机约束"""

    def setUp(self):
        self.editor = make_user('kb-editor@test.local', ['EDITOR'], '编辑部')
        self.other_editor = make_user(
            'kb-editor2@test.local', ['EDITOR'], '编辑部乙')
        self.reviewer = make_user('kb-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.author = make_user('kb-author@test.local', ['AUTHOR'], '作者')
        self.client = APIClient()

    def test_reviewer_forbidden(self):
        item = make_knowledge_item('RT-RV-00', status='PENDING_REVIEW')
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'APPROVED'}, format='json')
        self.assertEqual(resp.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.anonymization_status, 'PENDING_REVIEW')

    def test_author_forbidden(self):
        item = make_knowledge_item('RT-RV-00B', status='PENDING_REVIEW')
        self.client.force_authenticate(user=self.author)
        resp = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'APPROVED'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_approve_archives_irreversibly_with_notes(self):
        """P2 严重#5：审核备注 review_notes 必须真实落库"""
        item = make_knowledge_item('RT-RV-01', status='PENDING_REVIEW')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'APPROVED', 'notes': '匿名化处理到位，同意归档'},
            format='json')
        self.assertEqual(resp.status_code, 200)

        item.refresh_from_db()
        self.assertEqual(item.anonymization_status, 'APPROVED')
        self.assertIsNotNone(item.archived_at)
        self.assertEqual(item.reviewed_by, self.editor)
        self.assertIsNotNone(item.reviewed_at)
        self.assertEqual(item.review_notes, '匿名化处理到位，同意归档')
        # 归档后不允许再审核
        resp2 = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'REJECTED'}, format='json')
        self.assertEqual(resp2.status_code, 400)

    def test_reject_then_reapprove(self):
        """REJECTED 可修改后重新提交审核"""
        item = make_knowledge_item('RT-RV-02', status='PENDING_REVIEW')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'REJECTED', 'notes': '摘要仍含机构名，退回'},
            format='json')
        self.assertEqual(resp.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.anonymization_status, 'REJECTED')
        self.assertEqual(item.review_notes, '摘要仍含机构名，退回')
        self.assertIsNone(item.archived_at)

        resp2 = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'APPROVED', 'notes': '复审通过'},
            format='json')
        self.assertEqual(resp2.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.anonymization_status, 'APPROVED')
        self.assertEqual(item.review_notes, '复审通过')

    def test_permanently_excluded_not_reviewable_again(self):
        item = make_knowledge_item(
            'RT-RV-03', status='PERMANENTLY_EXCLUDED')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'APPROVED'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_decision_rejected(self):
        item = make_knowledge_item('RT-RV-04', status='PENDING_REVIEW')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'MAYBE'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_missing_knowledge_id_returns_400(self):
        """既有行为：条目不存在时 ValueError 映射为 400（非 404）"""
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            '/api/knowledge/KI-20990101-9999/review/',
            {'decision': 'APPROVED'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('不存在', str(resp.data))

    def test_notes_default_empty_string_persisted(self):
        """不带 notes 审核时 review_notes 落库为空串（而非 null）"""
        item = make_knowledge_item('RT-RV-05', status='PENDING_REVIEW')
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'APPROVED'}, format='json')
        self.assertEqual(resp.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.review_notes, '')


class KnowledgeArchiveLifecycleApiTests(TestCase):
    """知识项创建主链（终审决策自动归档 → 人工审核 → 检索可见）的 API 级闭环"""

    DECISION_NOTES = (
        '本稿件研究问题明确、方法可靠，两位审稿人意见积极，符合接收标准。' * 4
    )

    def setUp(self):
        self.editor = make_user('kb-editor@test.local', ['EDITOR'], '编辑部')
        self.author = make_user('kb-author@test.local', ['AUTHOR'], '作者')
        self.client = APIClient()
        self.client.force_authenticate(user=self.editor)

    def test_decision_creates_item_then_review_publishes_to_search(self):
        task = make_task(self.author, status='SUMMARIZED')
        # 1) 终审决策触发第一阶段自动匿名化归档
        resp = self.client.post(
            f'/api/tasks/{task.task_id}/make_decision/',
            {'decision': 'ACCEPT', 'notes': self.DECISION_NOTES, 'publish': True},
            format='json')
        self.assertEqual(resp.status_code, 200)

        item = KnowledgeItem.objects.get(source_task_id=task.task_id)
        self.assertEqual(item.anonymization_status, 'PENDING_REVIEW')
        self.assertIsNone(item.archived_at)

        # 2) 归档条目进入编辑部待审核列表
        resp = self.client.get('/api/knowledge/pending_reviews/')
        self.assertEqual(resp.status_code, 200)
        pending_ids = {r['knowledge_id'] for r in resp.data['results']}
        self.assertIn(item.knowledge_id, pending_ids)

        # 3) 审稿人此时检索不到该条目（未 APPROVED）
        reviewer = make_user(
            'kb-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.client.force_authenticate(user=reviewer)
        resp = self.client.get(
            '/api/knowledge/search/', {'keyword': task.keywords[0]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 0)

        # 4) 编辑部审核通过（带备注）
        self.client.force_authenticate(user=self.editor)
        resp = self.client.post(
            f'/api/knowledge/{item.knowledge_id}/review/',
            {'decision': 'APPROVED', 'notes': '终审归档，匿名化复核通过'},
            format='json')
        self.assertEqual(resp.status_code, 200)

        # 5) 条目离开待审核列表，进入检索结果
        resp = self.client.get('/api/knowledge/pending_reviews/')
        self.assertNotIn(item.knowledge_id,
                         {r['knowledge_id'] for r in resp.data['results']})

        resp = self.client.get('/api/knowledge/search/')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(
            resp.data['results'][0]['knowledge_id'], item.knowledge_id)

        item.refresh_from_db()
        self.assertEqual(item.review_notes, '终审归档，匿名化复核通过')


class KnowledgeExportApiTests(TestCase):
    """导出端点：仅编辑部；仅 APPROVED；不含 source_task_id（防溯源）"""

    def setUp(self):
        self.editor = make_user('kb-editor@test.local', ['EDITOR'], '编辑部')
        self.reviewer = make_user('kb-reviewer@test.local', ['REVIEWER'], '审稿人')
        self.author = make_user('kb-author@test.local', ['AUTHOR'], '作者')
        self.client = APIClient()

    def test_reviewer_forbidden(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get('/api/knowledge/export/')
        self.assertEqual(resp.status_code, 403)

    def test_author_forbidden(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.get('/api/knowledge/export/')
        self.assertEqual(resp.status_code, 403)

    def test_editor_exports_approved_only_without_source_task_id(self):
        make_knowledge_item('RT-EXP-01', status='APPROVED')
        make_knowledge_item('RT-EXP-02', status='PENDING_REVIEW')
        make_knowledge_item('RT-EXP-03', status='REJECTED')

        self.client.force_authenticate(user=self.editor)
        resp = self.client.get('/api/knowledge/export/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['format'], 'json')
        row = resp.data['data'][0]
        self.assertNotIn('source_task_id', row)
        self.assertIn('anonymized_summary', row)
        self.assertIn('knowledge_id', row)
