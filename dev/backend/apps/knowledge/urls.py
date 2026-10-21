"""
审稿知识库URL配置 - 对应PRD §3.1.12 审稿知识库功能

路由（挂载于 api/knowledge/）：
- GET    knowledge/search/                    检索知识库（审稿人+编辑部）
- GET    knowledge/<str:knowledge_id>/detail/ 查看详情（记录访问日志）
- GET    knowledge/pending_reviews/           待审核列表（仅编辑部）
- POST   knowledge/<str:knowledge_id>/review/ 审核匿名化（仅编辑部）
- GET    knowledge/export/                    导出数据（仅编辑部）

注：模板管理已在tasks app中实现（TemplateViewSet），此处不重复。
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import KnowledgeViewSet

router = DefaultRouter()
router.register(r'knowledge', KnowledgeViewSet, basename='knowledge')

urlpatterns = [
    # 检索知识库（审稿人+编辑部可用）
    path('knowledge/search/', KnowledgeViewSet.as_view({'get': 'search'}),
         name='knowledge-search'),
    # 待审核列表（仅编辑部）
    path('knowledge/pending_reviews/', KnowledgeViewSet.as_view({'get': 'pending_reviews'}),
         name='knowledge-pending-reviews'),
    # 导出数据（仅编辑部）
    path('knowledge/export/', KnowledgeViewSet.as_view({'get': 'export'}),
         name='knowledge-export'),
    # 查看详情（记录访问日志）
    path('knowledge/<str:knowledge_id>/detail/', KnowledgeViewSet.as_view({'get': 'detail'}),
         name='knowledge-detail'),
    # 审核匿名化（仅编辑部）
    path('knowledge/<str:knowledge_id>/review/', KnowledgeViewSet.as_view({'post': 'review_anonymization'}),
         name='knowledge-review'),
    # router标准路由
    path('', include(router.urls)),
]
