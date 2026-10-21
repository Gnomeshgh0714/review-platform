"""文件模块URL配置

路由前缀：files/
- POST   files/upload/                      上传PDF文件
- GET    files/<file_id>/download/          下载文件
- GET    files/<file_id>/check_metadata/    检查PDF元数据与匿名化
- DELETE files/<file_id>/                   删除文件
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FileViewSet

router = DefaultRouter()
router.register(r'files', FileViewSet, basename='file')

urlpatterns = [
    # 注册router（提供默认CRUD + destroy，其中list/retrieve已在视图中禁用）
    path('', include(router.urls)),
    # 显式声明自定义动作路径（确保URL可读性，也可通过router自动生成）
    path('files/upload/', FileViewSet.as_view({'post': 'upload'}), name='file-upload'),
    path('files/<str:file_id>/download/',
         FileViewSet.as_view({'get': 'download'}), name='file-download'),
    path('files/<str:file_id>/check_metadata/',
         FileViewSet.as_view({'get': 'check_metadata'}), name='file-check-metadata'),
]
