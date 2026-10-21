from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('', include(router.urls)),
    path('users/login/', UserViewSet.as_view({'post': 'login'}), name='login'),
    path('users/me/', UserViewSet.as_view({'get': 'me'}), name='me'),
    path('users/update_profile/', UserViewSet.as_view({'put': 'update_profile'}), name='update_profile'),
    path('users/reviewers/', UserViewSet.as_view({'get': 'reviewers'}), name='reviewers'),
]
