from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('', include(router.urls)),
    # #016 安全项3：refresh_token 刷新端点（simplejwt TokenRefreshView）；
    # settings 已开 ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION，刷新即轮换
    # ——响应体同时返回新 access 与新 refresh，旧 refresh 随即拉黑
    path('users/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('users/login/', UserViewSet.as_view({'post': 'login'}), name='login'),
    path('users/me/', UserViewSet.as_view({'get': 'me'}), name='me'),
    path('users/update_profile/', UserViewSet.as_view({'put': 'update_profile'}), name='update_profile'),
    path('users/reviewers/', UserViewSet.as_view({'get': 'reviewers'}), name='reviewers'),
]
