from django.db import models
from apps.users.models import User


class UploadedFile(models.Model):
    """文件上传记录"""

    file_id = models.BigAutoField(primary_key=True)
    original_name = models.CharField('原始文件名', max_length=255)
    file_path = models.CharField('存储路径', max_length=500)
    file_size = models.BigIntegerField('文件大小(字节)')
    file_type = models.CharField('文件类型', max_length=50, default='PDF')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='上传人')
    uploaded_at = models.DateTimeField('上传时间', auto_now_add=True)
    # PDF元数据检查（双盲模式）
    pdf_metadata_author = models.CharField('PDF元数据作者', max_length=200, blank=True)
    metadata_warning = models.BooleanField('元数据警告', default=False)
