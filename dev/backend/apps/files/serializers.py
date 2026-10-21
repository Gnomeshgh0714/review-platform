"""文件模块序列化器"""

from rest_framework import serializers
from .models import UploadedFile


class UploadedFileSerializer(serializers.ModelSerializer):
    """文件上传记录序列化器 - 用于序列化完整的文件记录"""

    # 展示上传人姓名（只读）
    uploaded_by_name = serializers.CharField(
        source='uploaded_by.name', read_only=True, default='未知'
    )

    class Meta:
        model = UploadedFile
        fields = [
            'file_id', 'original_name', 'file_path', 'file_size',
            'file_type', 'uploaded_by', 'uploaded_by_name', 'uploaded_at',
            'pdf_metadata_author', 'metadata_warning',
        ]
        read_only_fields = [
            'file_id', 'file_path', 'file_size', 'file_type',
            'uploaded_by', 'uploaded_at', 'pdf_metadata_author', 'metadata_warning',
        ]


class FileUploadResponseSerializer(serializers.Serializer):
    """文件上传成功响应序列化器 - 上传成功后返回精简信息"""

    file_id = serializers.IntegerField(read_only=True, help_text='文件ID')
    file_path = serializers.CharField(read_only=True, help_text='文件存储相对路径')
    original_name = serializers.CharField(read_only=True, help_text='原始文件名')
    file_size = serializers.IntegerField(read_only=True, help_text='文件大小(字节)')
    metadata_warning = serializers.BooleanField(read_only=True, help_text='元数据警告: True表示PDF元数据中含作者信息(双盲模式下需处理)')
