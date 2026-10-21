"""通知模块URL配置 - 对应PRD §3.1.10 notifications"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.notifications.views import NotificationViewSet

# 注册router，路径：notifications/
router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('', include(router.urls)),
    # 额外路径（与router注册的自定义action一致，显式声明便于清晰路由）
    path('notifications/unread_count/', NotificationViewSet.as_view({
        'get': 'unread_count',
    }), name='notification-unread-count'),
    path('notifications/mark_read/', NotificationViewSet.as_view({
        'post': 'mark_read',
    }), name='notification-mark-read'),
    path('notifications/mark_all_read/', NotificationViewSet.as_view({
        'post': 'mark_all_read',
    }), name='notification-mark-all-read'),
]
