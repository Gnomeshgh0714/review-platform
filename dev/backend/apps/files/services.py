"""文件模块业务服务层

负责PDF文件的上传校验、存储、元数据检查、匿名化检查与删除等核心业务逻辑。
"""

import os
import logging
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage

import PyPDF2
from PyPDF2 import PdfReader

from apps.files.models import UploadedFile

logger = logging.getLogger(__name__)

# 文件大小上限：20MB
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
# 允许的文件扩展名
ALLOWED_EXTENSIONS = ['.pdf']
# 允许的Content-Type
ALLOWED_CONTENT_TYPES = ['application/pdf']


class FileService:
    """文件服务类 - 封装文件上传、下载、元数据检查、删除等业务逻辑"""

    # ============================================================
    # 1. 文件上传
    # ============================================================
    @staticmethod
    def upload_pdf(file, user) -> UploadedFile:
        """上传PDF文件

        :param file: Django UploadedFile 对象
        :param user: 当前登录用户
        :return: UploadedFile 记录
        :raises ValueError: 文件格式或大小校验失败
        """
        # ---------- 1. 校验文件格式 ----------
        original_name = file.name
        _, ext = os.path.splitext(original_name)
        ext = ext.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f'仅支持PDF文件，当前文件类型: {ext or "未知"}')

        # 同时检查Content-Type（部分浏览器会伪造扩展名）
        content_type = getattr(file, 'content_type', '') or ''
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            # content_type可能为空，仅在不为空时校验
            logger.warning(f'文件Content-Type异常: {content_type}, 文件名: {original_name}')

        # ---------- 2. 校验文件大小 ----------
        file_size = file.size
        if file_size > MAX_FILE_SIZE:
            raise ValueError(
                f'文件大小超过限制(20MB)，当前大小: {file_size / 1024 / 1024:.2f}MB'
            )
        if file_size == 0:
            raise ValueError('文件为空，请重新上传')

        # ---------- 3. 构建存储路径：MEDIA_ROOT/uploads/YYYY/MM/DD/ ----------
        now = datetime.now()
        date_dir = now.strftime('%Y/%m/%d')
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads', date_dir)
        os.makedirs(upload_dir, exist_ok=True)

        # 生成唯一文件名（避免重名覆盖）：时间戳 + 原始名
        timestamp = now.strftime('%Y%m%d%H%M%S%f')
        safe_name = f'{timestamp}_{original_name}'
        full_disk_path = os.path.join(upload_dir, safe_name)

        # 写入磁盘（使用chunks避免大文件占内存）
        try:
            with open(full_disk_path, 'wb') as f:
                for chunk in file.chunks():
                    f.write(chunk)
        except IOError as e:
            logger.error(f'文件写入磁盘失败: {e}')
            raise ValueError(f'文件保存失败: {e}')

        # 相对路径（存入数据库，用于后续访问）
        relative_path = os.path.relpath(full_disk_path, settings.MEDIA_ROOT)

        # ---------- 4. 读取PDF元数据中的作者字段 ----------
        pdf_author = ''
        metadata_warning = False
        try:
            with open(full_disk_path, 'rb') as f:
                reader = PdfReader(f)
                metadata = reader.metadata
                if metadata:
                    # PyPDF2元数据字段名通常为 /Author
                    author = metadata.get('/Author') or metadata.get('/author') or ''
                    if author:
                        pdf_author = str(author).strip()
                        # 作者字段非空 -> 触发双盲匿名化警告
                        metadata_warning = True
                        logger.info(
                            f'PDF元数据含作者信息: file={original_name}, author={pdf_author}'
                        )
        except Exception as e:
            # PDF元数据读取失败不应阻断上传流程，仅记录日志
            logger.warning(f'PDF元数据读取失败(不阻断上传): file={original_name}, error={e}')

        # ---------- 5. 创建数据库记录 ----------
        uploaded_file = UploadedFile.objects.create(
            original_name=original_name,
            file_path=relative_path,
            file_size=file_size,
            file_type='PDF',
            uploaded_by=user,
            pdf_metadata_author=pdf_author,
            metadata_warning=metadata_warning,
        )

        logger.info(
            f'文件上传成功: id={uploaded_file.file_id}, name={original_name}, '
            f'size={file_size}, user={user.user_id if hasattr(user, "user_id") else user}'
        )
        return uploaded_file

    # ============================================================
    # 2. 获取文件路径（鉴权后中转下载）
    # ============================================================
    @staticmethod
    def check_download_permission(uploaded_file, user):
        """对象级下载权限（对应评审意见 V1.1 严重#4）：
        编辑部 / 上传人 / 稿件作者 / 被分配审稿人 四类主体可访问，
        其余登录用户拒绝（防止枚举 file_id 批量拉取他人稿件）。

        :param uploaded_file: UploadedFile 实例
        :param user: 当前登录用户
        :raises PermissionDenied: 无权访问
        """
        if user.is_editor:
            return
        if uploaded_file.uploaded_by_id == user.user_id:
            return
        # 文件与任务的关联：ReviewTask.manuscript_file 存储同一相对路径
        from apps.tasks.models import ReviewTask, ReviewAssignment
        related_tasks = ReviewTask.objects.filter(
            manuscript_file=uploaded_file.file_path,
        )
        if related_tasks.filter(author_user_id=user.user_id).exists():
            return
        # 评审意见 V1.2 严重#7：审稿人通道校验分配状态——仅「有效参与中」
        # （已接受/审稿中/已提交）放行；未响应(INVITED)、已拒绝、已过期或被
        # 标记 EXPIRED/OVERDUE 的分配不再保有下载权
        if ReviewAssignment.objects.filter(
            reviewer=user, task__in=related_tasks,
            assignment_status__in=['ACCEPTED', 'REVIEWING', 'SUBMITTED'],
        ).exists():
            return
        raise PermissionDenied('无权访问此文件（仅任务相关人或编辑部可下载）')

    @staticmethod
    def get_file_path(file_id, user) -> str:
        """获取文件的磁盘绝对路径（供中转下载使用）

        :param file_id: 文件ID
        :param user: 当前登录用户
        :return: 文件磁盘绝对路径
        :raises FileNotFoundError: 文件不存在
        :raises PermissionDenied: 无权访问
        """
        try:
            uploaded_file = UploadedFile.objects.get(file_id=file_id)
        except UploadedFile.DoesNotExist:
            raise FileNotFoundError(f'文件不存在: file_id={file_id}')

        # 对象级权限：技术方案 §1.5「按角色验证下载权限」
        FileService.check_download_permission(uploaded_file, user)

        # 构建磁盘绝对路径
        abs_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.file_path)

        # 校验文件在磁盘上是否真实存在
        if not os.path.exists(abs_path):
            logger.error(f'文件记录存在但磁盘文件丢失: file_id={file_id}, path={abs_path}')
            raise FileNotFoundError(f'文件资源不存在: file_id={file_id}')

        return abs_path

    # ============================================================
    # 3. 双盲匿名化检查
    # ============================================================
    @staticmethod
    def check_anonymization_checklist(file_path) -> dict:
        """双盲匿名化检查清单

        P0阶段仅检查PDF元数据中的作者字段。
        后续阶段可扩展：检查正文中的作者署名、致谢、基金信息、PDF注释等。

        :param file_path: 文件磁盘绝对路径
        :return: dict 检查清单结果
            {
                'passed': bool,           # 是否通过全部检查
                'checks': [               # 检查项列表
                    {
                        'item': str,       # 检查项名称
                        'status': str,     # 'pass' | 'warning' | 'fail'
                        'detail': str,     # 检查详情
                    },
                    ...
                ],
                'summary': str,            # 总结说明
            }
        """
        checks = []

        # ---------- 检查项1: PDF元数据作者字段 ----------
        author = ''
        status = 'pass'
        detail = '未检测到作者元数据'
        try:
            with open(file_path, 'rb') as f:
                reader = PdfReader(f)
                metadata = reader.metadata
                if metadata:
                    author = metadata.get('/Author') or metadata.get('/author') or ''
                    if author:
                        author = str(author).strip()
                        status = 'warning'
                        detail = f'PDF元数据中包含作者信息: "{author}"，双盲模式下建议清除'
                    else:
                        status = 'pass'
                        detail = 'PDF元数据中未包含作者信息'
                else:
                    status = 'pass'
                    detail = 'PDF无元数据'
        except Exception as e:
            status = 'warning'
            detail = f'PDF元数据读取失败: {e}（无法确认是否匿名化）'

        checks.append({
            'item': 'PDF元数据作者字段',
            'status': status,
            'detail': detail,
            'value': author,
        })

        # ---------- P0阶段：仅此一项检查 ----------
        # 后续可在此追加更多检查项：
        # - 正文中作者署名
        # - 致谢段落
        # - 基金资助信息
        # - PDF内嵌注释
        # - 文件属性中的其他字段（Title, Subject, Creator, Producer等）

        passed = all(c['status'] == 'pass' for c in checks)
        warning_count = sum(1 for c in checks if c['status'] == 'warning')
        fail_count = sum(1 for c in checks if c['status'] == 'fail')

        if passed:
            summary = '匿名化检查通过'
        else:
            summary = f'匿名化检查存在{warning_count}项警告、{fail_count}项不通过，请处理后再提交'

        return {
            'passed': passed,
            'checks': checks,
            'summary': summary,
        }

    # ============================================================
    # 4. 删除文件
    # ============================================================
    @staticmethod
    def delete_file(file_id, user) -> bool:
        """删除文件

        权限：仅文件上传人或编辑部角色可删除。

        :param file_id: 文件ID
        :param user: 当前登录用户
        :return: True表示删除成功
        :raises FileNotFoundError: 文件不存在
        :raises PermissionDenied: 无权删除
        """
        try:
            uploaded_file = UploadedFile.objects.get(file_id=file_id)
        except UploadedFile.DoesNotExist:
            raise FileNotFoundError(f'文件不存在: file_id={file_id}')

        # ---------- 权限校验：上传人或编辑部 ----------
        is_owner = uploaded_file.uploaded_by_id == user.user_id if hasattr(user, 'user_id') else uploaded_file.uploaded_by_id == user.id
        is_editor = hasattr(user, 'is_editor') and user.is_editor

        if not (is_owner or is_editor):
            raise PermissionDenied('无权删除此文件，仅上传人或编辑部可删除')

        # ---------- 删除磁盘文件 ----------
        abs_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.file_path)
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except OSError as e:
                logger.warning(f'磁盘文件删除失败(继续删除数据库记录): path={abs_path}, error={e}')

        # ---------- 删除数据库记录 ----------
        uploaded_file.delete()
        logger.info(f'文件删除成功: file_id={file_id}, operator={user.user_id if hasattr(user, "user_id") else user}')
        return True
