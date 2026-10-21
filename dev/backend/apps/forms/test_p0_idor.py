"""P0安全修复回归测试 - task_opinions IDOR（对应评审意见 V1.1 严重#3）

作者只能查看自己稿件的审稿意见；访问他人稿件的意见必须 403。
"""
from datetime import date, timedelta

from django.utils import timezone

from rest_framework.test import APIClient

from django.test import TestCase

from apps.forms.models import ReviewForm, ReviewOpinion
from apps.tasks.models import ReviewTask, Template, ReviewAssignment
from apps.users.models import User


def make_user(email, roles, name):
    return User.objects.create(email=email, name=name, roles=roles)


def make_decided_task(author, title):
    template = Template.objects.create(
        template_name=f'模板-{title}', template_type='SYSTEM_DEFAULT',
        dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
    )
    return ReviewTask.objects.create(
        title=title, abstract='摘要', keywords=['关键词一', '关键词二', '关键词三'],
        subject_area='经济学', manuscript_type='论文',
        manuscript_file=f'{title}.pdf', review_mode='DOUBLE_BLIND',
        deadline=date.today() + timedelta(days=14),
        template_id=template.template_id, author_user_id=author,
        status='DECIDED', final_decision='ACCEPT',
        publish_opinions_to_author=True,
    )


def make_submitted_opinion(task, reviewer):
    form = ReviewForm.objects.create(
        task=task, template_id=task.template_id,
        dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
    )
    assignment = ReviewAssignment.objects.create(
        task=task, reviewer=reviewer,
        deadline=date.today() + timedelta(days=14),
        invitation_expiry=date.today() + timedelta(days=3),
        assignment_status='SUBMITTED', submitted_at=timezone.now(),
    )
    return ReviewOpinion.objects.create(
        task=task, form=form, assignment=assignment, reviewer=reviewer,
        dimension_scores=[{'dimensionId': 'D1', 'score': 4, 'comment': '扎实'}],
        recommendation='ACCEPT', overall_comment='整体质量不错',
        status='SUBMITTED', submitted_at=timezone.now(),
    )


class TaskOpinionsIdorTests(TestCase):

    def setUp(self):
        self.editor = make_user('editor@test.local', ['EDITOR'], '编辑部')
        self.author_a = make_user('a@test.local', ['AUTHOR'], '作者甲')
        self.author_b = make_user('b@test.local', ['AUTHOR'], '作者乙')
        self.reviewer = make_user('r@test.local', ['REVIEWER'], '审稿人甲')

        self.task_a = make_decided_task(self.author_a, '稿件A')
        self.task_b = make_decided_task(self.author_b, '稿件B')
        self.opinion_a = make_submitted_opinion(self.task_a, self.reviewer)
        self.opinion_b = make_submitted_opinion(self.task_b, self.reviewer)
        self.client = APIClient()

    def test_author_cannot_read_others_task_opinions(self):
        """严重#3：作者甲带 task_id 枚举作者乙稿件的意见 -> 403"""
        self.client.force_authenticate(user=self.author_a)
        resp = self.client.get(
            '/api/opinions/task_opinions/', {'task_id': self.task_b.task_id})
        self.assertEqual(resp.status_code, 403)

    def test_author_reads_own_task_opinions_anonymized(self):
        self.client.force_authenticate(user=self.author_a)
        resp = self.client.get(
            '/api/opinions/task_opinions/', {'task_id': self.task_a.task_id})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['is_anonymized'])
        self.assertEqual(resp.data['count'], 1)
        # 匿名化口径：不含审稿人身份
        for opinion in resp.data['results']:
            self.assertNotIn('reviewer', opinion)
            self.assertNotIn('reviewer_name', opinion)
            self.assertNotIn('reviewer_email', opinion)
            self.assertNotIn('审稿人甲', str(opinion))

    def test_reviewer_cannot_access_task_opinions(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get(
            '/api/opinions/task_opinions/', {'task_id': self.task_a.task_id})
        self.assertEqual(resp.status_code, 403)

    def test_editor_sees_all_with_identity(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get(
            '/api/opinions/task_opinions/', {'task_id': self.task_a.task_id})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['is_anonymized'])
        self.assertEqual(resp.data['results'][0]['reviewer_name'], '审稿人甲')
