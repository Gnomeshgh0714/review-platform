from rest_framework import serializers
from .models import User


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

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class UserCreateSerializer(serializers.ModelSerializer):
    """创建用户序列化器（编辑部创建审稿人/作者账号）"""
    password = serializers.CharField(
        write_only=True, required=False,
        style={'input_type': 'password'},
        help_text='可选，缺省为 changeme123（首次登录后应尽快修改）',
    )

    class Meta:
        model = User
        fields = ['name', 'email', 'roles', 'institution', 'research_areas', 'password']
        extra_kwargs = {
            'name': {'required': True},
            'email': {'required': True},
            'roles': {'required': True},
        }

    def create(self, validated_data):
        # 未传密码时设默认密码，保证账号可登录
        password = validated_data.pop('password', None)
        user = User(**validated_data)
        user.set_password(password or 'changeme123')
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


class LoginSerializer(serializers.Serializer):
    """登录序列化器"""
    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'})
