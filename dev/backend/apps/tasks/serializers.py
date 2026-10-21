from rest_framework import serializers
from .models import ReviewTask, ReviewAssignment, Template, StateLog


class TemplateSerializer(serializers.ModelSerializer):
    """审稿模板序列化器"""

    class Meta:
        model = Template
        fields = ['template_id', 'template_name', 'template_type', 'subject_area',
                  'dimensions', 'status', 'created_by', 'created_at', 'updated_at']
        read_only_fields = ['template_id', 'created_at', 'updated_at']


class ReviewAssignmentSerializer(serializers.ModelSerializer):
    """审稿分配记录序列化器"""
    reviewer_name = serializers.CharField(source='reviewer.name', read_only=True)
    reviewer_email = serializers.CharField(source='reviewer.email', read_only=True)
    reviewer_research_areas = serializers.JSONField(source='reviewer.research_areas', read_only=True)
    task_title = serializers.CharField(source='task.title', read_only=True)

    class Meta:
        model = ReviewAssignment
        fields = ['assignment_id', 'task', 'task_title', 'reviewer', 'reviewer_name',
                  'reviewer_email', 'reviewer_research_areas', 'deadline',
                  'invitation_note', 'invitation_expiry', 'assignment_status',
                  'attempt_count', 'accepted_at', 'rejected_at', 'rejected_reason',
                  'submitted_at', 'assigned_by', 'assigned_at']
        read_only_fields = ['assignment_id', 'accepted_at', 'rejected_at',
                            'submitted_at', 'assigned_at', 'attempt_count']


class ReviewTaskSerializer(serializers.ModelSerializer):
    """审稿任务序列化器"""
    author_name = serializers.CharField(source='author_user_id.name', read_only=True)
    author_email = serializers.CharField(source='author_user_id.email', read_only=True)
    created_by_name = serializers.CharField(source='created_by.name', read_only=True)
    template_name = serializers.SerializerMethodField()
    assignments = ReviewAssignmentSerializer(many=True, read_only=True)

    class Meta:
        model = ReviewTask
        fields = ['task_id', 'title', 'abstract', 'keywords', 'subject_area',
                  'manuscript_type', 'manuscript_file', 'review_mode',
                  'expected_reviewer_count', 'deadline', 'additional_notes',
                  'template_id', 'author_user_id', 'author_name', 'author_email',
                  'status', 'final_decision', 'decision_notes',
                  'publish_opinions_to_author', 'created_by', 'created_by_name',
                  'template_name', 'retry_count', 'version',
                  'assignments', 'created_at', 'updated_at']
        # 评审意见 V1.2 致命#2/严重#9：manuscript_file/review_mode/
        # publish_opinions_to_author 经 PATCH 可击穿双盲裁剪与发布门控，
        # 并与 ai_review 的路径读取链组合成任意文件读取，任务一经创建即只读
        read_only_fields = ['task_id', 'status', 'final_decision', 'decision_notes',
                            'manuscript_file', 'review_mode', 'publish_opinions_to_author',
                            'retry_count', 'version', 'created_at', 'updated_at']

    def get_template_name(self, obj):
        try:
            tpl = Template.objects.get(template_id=obj.template_id)
            return tpl.template_name
        except Template.DoesNotExist:
            return None

    def to_representation(self, instance):
        """按调用者角色与审稿模式裁剪身份字段（PRD AC-T-13 双盲保护）：
        - 作者视角：任何模式下不可见审稿人身份（单盲/双盲均如此）
        - 审稿人视角：双盲模式下不可见作者身份
        - 编辑部：可见全部；无请求上下文（内部调用）时按编辑部口径返回
        """
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is None:
            return data
        user = getattr(request, 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False) or user.is_editor:
            return data
        if instance.author_user_id == user:
            # 作者视角：抹去全部审稿人身份字段
            for assignment in data.get('assignments') or []:
                for key in ('reviewer', 'reviewer_name', 'reviewer_email',
                            'reviewer_research_areas'):
                    assignment.pop(key, None)
        elif user.is_reviewer and instance.review_mode == 'DOUBLE_BLIND':
            # 审稿人视角 + 双盲：抹去作者身份字段
            data.pop('author_name', None)
            data.pop('author_email', None)
        return data


class ReviewTaskCreateSerializer(serializers.ModelSerializer):
    """创建审稿任务序列化器"""

    class Meta:
        model = ReviewTask
        fields = ['title', 'abstract', 'keywords', 'subject_area',
                  'manuscript_type', 'manuscript_file', 'review_mode',
                  'expected_reviewer_count', 'deadline', 'additional_notes',
                  'template_id', 'author_user_id']

    def validate_expected_reviewer_count(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError('审稿人数量必须在1-5之间')
        return value

    def validate_keywords(self, value):
        if not isinstance(value, list) or not 3 <= len(value) <= 10:
            raise serializers.ValidationError('关键词必须3-10个')
        return value


class StateLogSerializer(serializers.ModelSerializer):
    """状态变更日志序列化器"""
    operator_name = serializers.CharField(source='operator_user.name', read_only=True, default='系统')

    class Meta:
        model = StateLog
        fields = ['log_id', 'task', 'from_state', 'to_state',
                  'operator_type', 'operator_name', 'trigger_reason', 'created_at']
