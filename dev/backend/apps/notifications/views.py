"""通知模块视图 - 对应PRD §3.1.10 notifications"""
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer, MarkReadSerializer


class NotificationViewSet(viewsets.GenericViewSet):
    """
    通知视图集 - 提供当前用户的通知列表、未读数、标记已读等操作。

    权限：IsAuthenticated，用户只能查看/操作自己的通知。
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """只返回当前用户的通知，支持is_read筛选"""
        queryset = Notification.objects.filter(user=self.request.user)
        # 支持is_read筛选：?is_read=true / ?is_read=false
        is_read = self.request.query_params.get('is_read', None)
        if is_read is not None:
            is_read_bool = is_read.lower() in ('true', '1', 'yes')
            queryset = queryset.filter(is_read=is_read_bool)
        return queryset.order_by('-created_at')

    def list(self, request):
        """
        获取当前用户的通知列表（支持is_read筛选、分页）

        GET /api/notifications/?is_read=false&page=1
        """
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """获取单条通知详情（仅限自己的通知）"""
        try:
            notification = self.get_queryset().get(pk=pk)
        except Notification.DoesNotExist:
            return Response(
                {'error': '通知不存在或无权访问'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = self.get_serializer(notification)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """
        获取当前用户的未读通知数量

        GET /api/notifications/unread_count/
        """
        count = self.get_queryset().filter(is_read=False).count()
        return Response({'unread_count': count})

    @action(detail=False, methods=['post'])
    def mark_read(self, request):
        """
        批量标记通知为已读 - POST body传notification_ids数组

        POST /api/notifications/mark_read/
        {
            "notification_ids": [1, 2, 3]
        }
        """
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notification_ids = serializer.validated_data['notification_ids']

        # 只能操作自己的通知，且仅更新未读的通知
        with transaction.atomic():
            updated = self.get_queryset().filter(
                notification_id__in=notification_ids,
                is_read=False,
            ).update(is_read=True)

        return Response({
            'message': '标记已读成功',
            'updated_count': updated,
        })

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """
        标记当前用户全部通知为已读

        POST /api/notifications/mark_all_read/
        """
        with transaction.atomic():
            updated = self.get_queryset().filter(
                is_read=False,
            ).update(is_read=True)

        return Response({
            'message': '全部标记已读成功',
            'updated_count': updated,
        })
