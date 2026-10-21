from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ReviewTaskViewSet, TemplateViewSet, init_default_templates

router = DefaultRouter()
router.register(r'tasks', ReviewTaskViewSet, basename='task')
router.register(r'templates', TemplateViewSet, basename='template')

urlpatterns = [
    path('', include(router.urls)),
    # 任务操作
    path('tasks/dashboard/', ReviewTaskViewSet.as_view({'get': 'dashboard'}), name='dashboard'),
    path('tasks/my_tasks/', ReviewTaskViewSet.as_view({'get': 'my_tasks'}), name='my_tasks'),
    path('tasks/my_articles/', ReviewTaskViewSet.as_view({'get': 'my_articles'}), name='my_articles'),
    path('tasks/<str:pk>/assign_reviewers/', ReviewTaskViewSet.as_view({'post': 'assign_reviewers'}), name='assign_reviewers'),
    path('tasks/<str:pk>/accept_invitation/', ReviewTaskViewSet.as_view({'post': 'accept_invitation'}), name='accept_invitation'),
    path('tasks/<str:pk>/reject_invitation/', ReviewTaskViewSet.as_view({'post': 'reject_invitation'}), name='reject_invitation'),
    path('tasks/<str:pk>/force_summarize/', ReviewTaskViewSet.as_view({'post': 'force_summarize'}), name='force_summarize'),
    path('tasks/<str:pk>/handle_overdue/', ReviewTaskViewSet.as_view({'post': 'handle_overdue'}), name='handle_overdue'),
    path('tasks/<str:pk>/make_decision/', ReviewTaskViewSet.as_view({'post': 'make_decision'}), name='make_decision'),
    path('tasks/<str:pk>/state_logs/', ReviewTaskViewSet.as_view({'get': 'state_logs'}), name='state_logs'),
    # 模板操作
    path('templates/<str:pk>/toggle_status/', TemplateViewSet.as_view({'post': 'toggle_status'}), name='toggle_status'),
]
