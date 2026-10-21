from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from .models import User
from .serializers import (
    UserSerializer, UserCreateSerializer, UserAdminSerializer,
    UserProfileSerializer, ChangePasswordSerializer, LoginSerializer,
)
from .throttling import LoginMinuteThrottle, LoginDailyThrottle


class UserViewSet(viewsets.ModelViewSet):
    """用户视图集 - 登录/个人信息 + 编辑部用户管理

    权限收口（对应评审意见 V1.1 致命#1/#2）：
    - login 匿名开放；me/update_profile/change_password 仅本人（登录即可）
    - list/create/update/partial_update/destroy/retrieve 仅编辑部（retrieve 另允许本人）
    - 角色与邮箱变更仅经编辑部通道（UserAdminSerializer），个人通道字段白名单
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action == 'login':
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ('update', 'partial_update'):
            return UserAdminSerializer
        if self.action == 'update_profile':
            return UserProfileSerializer
        if self.action == 'change_password':
            return ChangePasswordSerializer
        return UserSerializer

    def get_throttles(self):
        """#016 安全项1：仅登录接口限流（防暴力破解）——10 次/分钟/IP + 50 次/天/IP，
        超限返回 429；档位见 settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']。
        按 self.action 局部生效，其余接口不限流（含手动 as_view 注册的 login 路由）。
        """
        if self.action == 'login':
            return [LoginMinuteThrottle(), LoginDailyThrottle()]
        return super().get_throttles()

    # ==================== 编辑部用户管理 ====================

    def list(self, request, *args, **kwargs):
        """用户列表（仅编辑部）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可查看用户列表'}, status=403)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        """用户详情（仅编辑部或本人）"""
        if not request.user.is_editor and request.user.user_id != kwargs.get('pk'):
            return Response({'error': '仅可查看本人或经编辑部授权的用户信息'}, status=403)
        return super().retrieve(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """创建用户（仅编辑部，对应PRD §3.1.1 编辑部创建审稿人/作者账号）"""
        if not request.user.is_editor:
            return Response(
                {'error': '仅编辑部可创建用户账号'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """更新用户（仅编辑部；可调整角色/邮箱/重置密码）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可管理用户账号'}, status=403)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """部分更新用户（仅编辑部）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可管理用户账号'}, status=403)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """删除用户（仅编辑部）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可删除用户账号'}, status=403)
        return super().destroy(request, *args, **kwargs)

    # ==================== 本人操作 ====================

    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def login(self, request):
        """用户登录 - 返回JWT token

        #016 安全项1：登录限流（防暴力破解）——10 次/分钟/IP + 50 次/天/IP，
        超限返回 429；正常使用与 E2E 冒烟（5 次登录）均在限值内。
        """
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        user = authenticate(request, username=email, password=password)
        if user is None:
            try:
                user_obj = User.objects.get(email=email)
                if user_obj.check_password(password):
                    user = user_obj
            except User.DoesNotExist:
                pass

        if user is None:
            return Response(
                {'error': '邮箱或密码错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        })

    @action(detail=False, methods=['get'])
    def me(self, request):
        """获取当前登录用户信息"""
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=['put'])
    def update_profile(self, request):
        """更新个人基础资料（仅 name/institution/research_areas，不含邮箱/角色/密码）"""
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        """修改本人密码（需校验旧密码）"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password', 'updated_at'])
        return Response({'message': '密码已修改，请使用新密码重新登录'})

    # ==================== 编辑部检索 ====================

    @action(detail=False, methods=['get'])
    def reviewers(self, request):
        """获取审稿人列表（编辑部搜索审稿人用）- 支持标签匹配排序"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可访问'}, status=403)

        reviewers = User.objects.filter(roles__contains=['REVIEWER'])

        # 关键词搜索
        keyword = request.query_params.get('keyword', '').strip()
        if keyword:
            from django.db.models import Q
            reviewers = reviewers.filter(
                Q(name__icontains=keyword) |
                Q(institution__icontains=keyword) |
                Q(research_areas__contains=[keyword])
            )

        # 学科筛选
        subject = request.query_params.get('subject', '').strip()
        if subject:
            reviewers = reviewers.filter(research_areas__contains=[subject])

        # 标签匹配排序：稿件关键词 × 审稿人researchAreas
        task_keywords = request.query_params.get('task_keywords', '')
        if task_keywords:
            kw_list = [k.strip() for k in task_keywords.split(',') if k.strip()]

            def match_score(reviewer):
                areas = set(reviewer.research_areas or [])
                return sum(1 for kw in kw_list if kw in areas)

            reviewers = sorted(reviewers, key=match_score, reverse=True)

        serializer = UserSerializer(reviewers, many=True)
        return Response({
            'count': len(serializer.data),
            'results': serializer.data,
        })
