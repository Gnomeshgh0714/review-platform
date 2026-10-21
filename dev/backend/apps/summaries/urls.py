"""
汇总报告URL配置 - 对应PRD §3.1.6 审稿意见汇总功能

路由（挂载于 api/summaries/）：
- GET    summaries/                          汇总报告列表（编辑部）
- POST   summaries/generate/                 触发汇总报告生成（仅编辑部，任务需SUBMITTED）
- GET    summaries/<str:task_id>/detail/     查看汇总报告详情（通过task_id）
- GET    summaries/<str:report_id>/          查看汇总报告详情（通过report_id，router标准路由）
- POST   summaries/match_rule_preview/       预览规则匹配结果（调试用）
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SummaryReportViewSet

router = DefaultRouter()
router.register(r'summaries', SummaryReportViewSet, basename='summary-report')

urlpatterns = [
    # 触发汇总报告生成（仅编辑部，任务需为SUBMITTED状态）
    path('summaries/generate/', SummaryReportViewSet.as_view({'post': 'generate'}),
         name='summary-generate'),
    # 预览规则匹配结果（调试用，不生成报告）
    path('summaries/match_rule_preview/', SummaryReportViewSet.as_view({'post': 'match_rule_preview'}),
         name='summary-match-rule-preview'),
    # 查看汇总报告详情（通过 task_id）
    path('summaries/<str:task_id>/detail/', SummaryReportViewSet.as_view({'get': 'detail'}),
         name='summary-detail-by-task'),
    # router标准路由：列表(GET summaries/) + 详情(GET summaries/<report_id>/)
    path('', include(router.urls)),
]
