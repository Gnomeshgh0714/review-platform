"""P0安全修复回归测试 - 文件下载/元数据对象级权限（对应评审意见 V1.1 严重#4）

无关登录用户不可通过枚举 file_id 拉取他人稿件；编辑部/上传人/稿件作者/被分配审稿人可访问。
权限校验先于磁盘存在性检查（记录在、盘上无文件时：有权者 404/200，无权者 403）。
"""
from datetime import date, timedelta

from rest_framework.test import APIClient

from django.test import TestCase

from apps.files.models import UploadedFile
from apps.tasks.models import ReviewTask, Template, ReviewAssignment
from apps.users.models import User


def make_user(email, roles, name):
    return User.objects.create(email=email, name=name, roles=roles)


class FilePermissionTests(TestCase):

    def setUp(self):
        self.editor = make_user('editor@test.local', ['EDITOR'], '编辑部')
        self.uploader = make_user('uploader@test.local', ['EDITOR'], '上传编辑')
        self.author = make_user('author@test.local', ['AUTHOR'], '作者甲')
        self.reviewer = make_user('reviewer@test.local', ['REVIEWER'], '审稿人甲')
        self.outsider = make_user('outsider@test.local', ['AUTHOR'], '无关用户')

        # 磁盘上不存在对应文件：权限分支在磁盘检查之前，应先返回 403/放行
        self.uploaded = UploadedFile.objects.create(
            original_name='manuscript.pdf',
            file_path='uploads/2026/10/16/fake_manuscript.pdf',
            file_size=1024, file_type='PDF', uploaded_by=self.uploader,
        )

        template = Template.objects.create(
            template_name='模板', template_type='SYSTEM_DEFAULT',
            dimensions=[{'dimensionId': 'D1', 'dimensionName': '研究意义'}],
        )
        self.task = ReviewTask.objects.create(
            title='关联稿件', abstract='摘要', keywords=['a', 'b', 'c'],
            subject_area='经济学', manuscript_type='论文',
            manuscript_file=self.uploaded.file_path,  # 任务与文件同路径关联
            review_mode='DOUBLE_BLIND',
            deadline=date.today() + timedelta(days=14),
            template_id=template.template_id, author_user_id=self.author,
            status='REVIEWING',
        )
        self.assignment = ReviewAssignment.objects.create(
            task=self.task, reviewer=self.reviewer,
            deadline=date.today() + timedelta(days=14),
            invitation_expiry=date.today() + timedelta(days=3),
            assignment_status='ACCEPTED',
        )
        self.client = APIClient()

    # ---------- 无关用户被拒 ----------

    def test_outsider_cannot_download(self):
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.get(f'/api/files/{self.uploaded.file_id}/download/')
        self.assertEqual(resp.status_code, 403)

    def test_outsider_cannot_check_metadata(self):
        self.client.force_authenticate(user=self.outsider)
        resp = self.client.get(f'/api/files/{self.uploaded.file_id}/check_metadata/')
        self.assertEqual(resp.status_code, 403)

    def test_author_of_unrelated_task_cannot_download(self):
        """另一稿件的作者同样无权（防止作者角色本身成为通行证）"""
        other = make_user('other@test.local', ['AUTHOR'], '作者乙')
        self.client.force_authenticate(user=other)
        resp = self.client.get(f'/api/files/{self.uploaded.file_id}/download/')
        self.assertEqual(resp.status_code, 403)

    # ---------- 有权主体放行（磁盘文件缺失时表现为 404，而非 403） ----------

    def test_editor_passes_permission_check(self):
        self.client.force_authenticate(user=self.editor)
        resp = self.client.get(f'/api/files/{self.uploaded.file_id}/download/')
        self.assertEqual(resp.status_code, 404)  # 过权限，卡在磁盘缺失

    def test_task_author_passes_permission_check(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(f'/api/files/{self.uploaded.file_id}/download/')
        self.assertEqual(resp.status_code, 404)  # 过权限，卡在磁盘缺失

    def test_assigned_reviewer_passes_permission_check(self):
        self.client.force_authenticate(user=self.reviewer)
        resp = self.client.get(f'/api/files/{self.uploaded.file_id}/download/')
        self.assertEqual(resp.status_code, 404)  # 过权限，卡在磁盘缺失

    def test_unassigned_reviewer_rejected(self):
        """审稿人角色本身不够：必须是被分配到该稿件任务的审稿人"""
        stranger = make_user('stranger@test.local', ['REVIEWER'], '审稿人乙')
        self.client.force_authenticate(user=stranger)
        resp = self.client.get(f'/api/files/{self.uploaded.file_id}/download/')
        self.assertEqual(resp.status_code, 403)

    def test_check_metadata_returns_200_for_task_author(self):
        self.client.force_authenticate(user=self.author)
        resp = self.client.get(f'/api/files/{self.uploaded.file_id}/check_metadata/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['file_id'], self.uploaded.file_id)
