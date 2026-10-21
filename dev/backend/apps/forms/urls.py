"""
审稿表单模块URL配置 - 对应PRD §6.2.4 / §6.2.5

路由清单：
- forms/              ：审稿表单（GenericViewSet，仅自定义action）
- opinions/           ：审稿意见（GenericViewSet，仅自定义action）

额外路径：
- forms/get_form/         ：GET 获取审稿表单（?task_id=xxx）
- opinions/submit/        ：POST 提交审稿意见
- opinions/save_draft/    ：POST 保存草稿
- opinions/my_opinion/    ：GET 获取当前审稿人的意见（?task_id=xxx）
- opinions/task_opinions/ ：GET 获取任务的所有审稿意见（?task_id=xxx）
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ReviewFormViewSet, ReviewOpinionViewSet

router = DefaultRouter()
router.register(r'forms', ReviewFormViewSet, basename='form')
router.register(r'opinions', ReviewOpinionViewSet, basename='opinion')

urlpatterns = [
    path('', include(router.urls)),
    # 审稿表单操作
    path('forms/get_form/', ReviewFormViewSet.as_view({'get': 'get_form'}),
         name='form-get-form'),
    path('forms/ai_review/', ReviewFormViewSet.as_view({'post': 'ai_review'}),
         name='form-ai-review'),
    path('forms/validate_references/', ReviewFormViewSet.as_view({'post': 'validate_references'}),
         name='form-validate-references'),
    # 审稿意见操作
    path('opinions/submit/', ReviewOpinionViewSet.as_view({'post': 'submit'}),
         name='opinion-submit'),
    path('opinions/save_draft/', ReviewOpinionViewSet.as_view({'post': 'save_draft'}),
         name='opinion-save-draft'),
    path('opinions/my_opinion/', ReviewOpinionViewSet.as_view({'get': 'my_opinion'}),
         name='opinion-my-opinion'),
    path('opinions/task_opinions/', ReviewOpinionViewSet.as_view({'get': 'task_opinions'}),
         name='opinion-task-opinions'),
]
