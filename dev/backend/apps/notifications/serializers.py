"""通知模块序列化器 - 对应PRD §3.1.10 notifications"""
from rest_framework import serializers
from apps.notifications.models import Notification
from apps.users.models import User
from apps.tasks.models import ReviewTask


class UserBriefSerializer(serializers.ModelSerializer):
    """用户简要信息（嵌套在通知中）"""

    class Meta:
        model = User
        fields = ['user_id', 'name', 'email', 'roles']
        # user_id 为只读主键
        read_only_fields = ['user_id']


class TaskBriefSerializer(serializers.ModelSerializer):
    """任务简要信息（嵌套在通知中）"""

    class Meta:
        model = ReviewTask
        fields = ['task_id', 'title', 'status', 'deadline', 'subject_area']
        read_only_fields = ['task_id']


class NotificationSerializer(serializers.ModelSerializer):
    """通知序列化器 - 包含用户信息和任务信息"""

    # 嵌套展示接收人信息
    user = UserBriefSerializer(read_only=True)
    # 嵌套展示关联任务信息（task 可为空）
    task = TaskBriefSerializer(read_only=True)
    # 通知类型展示文本
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'notification_id',
            'user',
            'task',
            'type',
            'type_display',
            'title',
            'content',
            'is_read',
            'created_at',
        ]
        read_only_fields = [
            'notification_id', 'user', 'task', 'type', 'type_display',
            'title', 'content', 'is_read', 'created_at',
        ]


class MarkReadSerializer(serializers.Serializer):
    """批量标记已读请求的序列化器 - 接收notification_ids数组"""
    notification_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text='需要标记为已读的通知ID列表',
    )
