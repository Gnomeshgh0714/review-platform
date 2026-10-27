from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import User


def blacklist_user_tokens(user):
    """V1.2 一般#22：将用户全部已签发 refresh token 加入黑名单（幂等），
    改密/重置密码后旧 refresh 立即失效；access 为无状态 JWT，最长 12h
    自然过期。供 change_password 与编辑部重置密码通道共用。"""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import RefreshToken
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
    for token in OutstandingToken.objects.filter(user=user):
        try:
            RefreshToken(token.token).blacklist()
        except TokenError:
            # 已过期/无法解析的 token 无需拉黑
            continue


class UserSerializer(serializers.ModelSerializer):
    """用户序列化器（仅响应展示：邮箱与角色为身份/权限字段，一律只读；
    角色变更仅经编辑部管理通道 UserAdminSerializer，防止自报提权）"""

    class Meta:
        model = User
        fields = ['user_id', 'name', 'email', 'roles', 'institution',
                  'research_areas', 'created_at', 'updated_at']
        read_only_fields = fields


class UserProfileSerializer(serializers.ModelSerializer):
    """个人资料更新序列化器（update_profile 专用：仅基础资料可改，
    邮箱/角色/密码不在此通道；改密走 change_password 并校验旧密码）"""

    class Meta:
        model = User
        fields = ['name', 'institution', 'research_areas']


class UserAdminSerializer(serializers.ModelSerializer):
    """编辑部用户管理序列化器（仅编辑部权限的 update/partial_update 使用，
    可调整角色/邮箱/重置密码）"""
    password = serializers.CharField(
        write_only=True, required=False,
        style={'input_type': 'password'},
        help_text='可选，传入即重置密码',
    )

    class Meta:
        model = User
        fields = ['name', 'email', 'roles', 'institution', 'research_areas', 'password']

    def validate_password(self, value):
        # V1.2 一般#32：编辑部重置密码通道接入 AUTH_PASSWORD_VALIDATORS
        #（settings 已定义但此前未接线任何通道）
        try:
            validate_password(value, self.instance)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        password_reset = bool(password)
        if password:
            instance.set_password(password)
        instance.save()
        if password_reset:
            # V1.2 一般#22：重置密码后旧 refresh token 一并拉黑
            blacklist_user_tokens(instance)
        return instance


class UserCreateSerializer(serializers.ModelSerializer):
    """创建用户序列化器（编辑部创建审稿人/作者账号）"""

    # 缺省初始密码：编辑部未显式传密码时使用。创建成功后随邀请邮件告知
    # 本人（PRD §6.2.1，接线见 apps/users/views.py 的 create），首次登录后
    # 应尽快修改；提为常量供邮件路径引用同一口径，避免双头维护
    DEFAULT_INITIAL_PASSWORD = 'changeme123'

    password = serializers.CharField(
        write_only=True, required=False,
        style={'input_type': 'password'},
        # 引用同常量拼入提示文本，常量变更时 help_text 不漂移（核验建议项）
        help_text=f'可选，缺省为 {DEFAULT_INITIAL_PASSWORD}（首次登录后应尽快修改）',
    )

    class Meta:
        model = User
        fields = ['name', 'email', 'roles', 'institution', 'research_areas', 'password']
        extra_kwargs = {
            'name': {'required': True},
            'email': {'required': True},
            'roles': {'required': True},
        }

    def validate_password(self, value):
        # V1.2 一般#32：创建用户通道接入 AUTH_PASSWORD_VALIDATORS；
        # 缺省默认密码不在此校验（见 create），但鼓励首次登录后修改
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def create(self, validated_data):
        # 未传密码时设默认密码，保证账号可登录
        password = validated_data.pop('password', None)
        user = User(**validated_data)
        user.set_password(password or self.DEFAULT_INITIAL_PASSWORD)
        user.is_active = True
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    """修改密码序列化器（需校验旧密码，防止会话被劫持后直接改密锁定账号）"""
    old_password = serializers.CharField(style={'input_type': 'password'})
    new_password = serializers.CharField(
        min_length=8, style={'input_type': 'password'},
        help_text='至少8位',
    )

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('旧密码错误')
        return value

    def validate_new_password(self, value):
        # V1.2 一般#32：自助改密通道接入 AUTH_PASSWORD_VALIDATORS
        #（含与用户属性相似度校验，需传 user 实例）
        try:
            validate_password(value, self.context['request'].user)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value


class LoginSerializer(serializers.Serializer):
    """登录序列化器"""
    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'})
