"""文件模块视图层

提供文件上传、下载、元数据检查接口。
所有接口均需登录认证（IsAuthenticated）。
"""

import os
import logging

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.core.exceptions import PermissionDenied
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import UploadedFile
from .serializers import UploadedFileSerializer, FileUploadResponseSerializer
from .services import FileService

logger = logging.getLogger(__name__)


class FileViewSet(viewsets.ModelViewSet):
    """文件视图集 - 上传/下载/元数据检查

    仅暴露 upload / download / check_metadata 三个自定义动作，
    不使用默认的 CRUD（文件生命周期由业务流程管理）。
    """

    queryset = UploadedFile.objects.all()
    serializer_class = UploadedFileSerializer
    permission_classes = [IsAuthenticated]

    # 默认禁用列表/详情接口（文件不直接暴露列表）
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def list(self, request, *args, **kwargs):
        """禁用列表接口"""
        return Response(
            {'error': '文件列表接口未开放'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def retrieve(self, request, *args, **kwargs):
        """禁用详情接口"""
        return Response(
            {'error': '请使用指定接口访问文件'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    # ============================================================
    # 1. 上传PDF文件
    # ============================================================
    @action(detail=False, methods=['post'], url_path='upload')
    def upload(self, request):
        """上传PDF文件

        请求格式：multipart/form-data
        字段：file (PDF文件)

        响应：
        {
            "file_id": 1,
            "file_path": "uploads/2026/07/17/xxx.pdf",
            "original_name": "manuscript.pdf",
            "file_size": 1234567,
            "metadata_warning": false
        }
        """
        file = request.FILES.get('file')
        if not file:
            return Response(
                {'error': '请上传文件，字段名: file'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            uploaded_file = FileService.upload_pdf(file, request.user)
        except ValueError as e:
            # 校验失败（格式/大小）
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f'文件上传异常: {e}', exc_info=True)
            return Response(
                {'error': f'文件上传失败: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        serializer = FileUploadResponseSerializer(uploaded_file)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # ============================================================
    # 2. 下载文件
    # ============================================================
    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        """下载文件（按file_id中转下载）

        路径参数：file_id (pk)
        返回：文件流
        """
        try:
            file_path = FileService.get_file_path(pk, request.user)
        except FileNotFoundError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_404_NOT_FOUND
            )
        except PermissionDenied as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_403_FORBIDDEN
            )

        # 获取原始文件名用于Content-Disposition
        try:
            uploaded_file = UploadedFile.objects.get(file_id=pk)
            original_name = uploaded_file.original_name
        except UploadedFile.DoesNotExist:
            original_name = os.path.basename(file_path)

        # 使用FileResponse流式返回文件
        try:
            file_handle = open(file_path, 'rb')
        except IOError as e:
            logger.error(f'文件打开失败: {e}')
            return Response(
                {'error': '文件读取失败'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        response = FileResponse(file_handle, content_type='application/pdf')
        # 设置下载文件名（支持中文）
        response['Content-Disposition'] = f'attachment; filename="{original_name}"'
        response['Content-Length'] = str(os.path.getsize(file_path))
        return response

    # ============================================================
    # 3. 检查PDF元数据
    # ============================================================
    @action(detail=True, methods=['get'], url_path='check_metadata')
    def check_metadata(self, request, pk=None):
        """检查PDF元数据（返回author字段和警告）+ 双盲匿名化检查清单

        路径参数：file_id (pk)
        响应：
        {
            "file_id": 1,
            "original_name": "manuscript.pdf",
            "pdf_metadata_author": "张三",
            "metadata_warning": true,
            "anonymization": { ... }   // 匿名化检查清单
        }
        """
        try:
            uploaded_file = UploadedFile.objects.get(file_id=pk)
        except UploadedFile.DoesNotExist:
            return Response(
                {'error': f'文件不存在: file_id={pk}'},
                status=status.HTTP_404_NOT_FOUND
            )

        # 对象级权限：与下载同口径（元数据含作者真实姓名，不应向无关用户暴露）
        try:
            FileService.check_download_permission(uploaded_file, request.user)
        except PermissionDenied as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_403_FORBIDDEN
            )

        # 获取磁盘绝对路径
        abs_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.file_path)

        # 运行匿名化检查清单
        if os.path.exists(abs_path):
            anonymization_result = FileService.check_anonymization_checklist(abs_path)
        else:
            anonymization_result = {
                'passed': False,
                'checks': [],
                'summary': '文件资源不存在，无法检查',
            }

        return Response({
            'file_id': uploaded_file.file_id,
            'original_name': uploaded_file.original_name,
            'pdf_metadata_author': uploaded_file.pdf_metadata_author,
            'metadata_warning': uploaded_file.metadata_warning,
            'anonymization': anonymization_result,
        })

    # ============================================================
    # 4. 删除文件（额外提供DELETE接口）
    # ============================================================
    def destroy(self, request, *args, **kwargs):
        """删除文件"""
        file_id = kwargs.get('pk')
        try:
            FileService.delete_file(file_id, request.user)
        except FileNotFoundError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_404_NOT_FOUND
            )
        except PermissionDenied as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_403_FORBIDDEN
            )
        except ValueError as e:
            # V1.2 一般#23：文件被审稿任务引用时删除被拒，返回 400
            #（引用检查见 FileService.delete_file）
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {'message': '文件删除成功'},
            status=status.HTTP_200_OK
        )
