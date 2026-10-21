"""
URL configuration for review_platform project.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('apps.users.urls')),
    path('api/', include('apps.tasks.urls')),
    path('api/', include('apps.notifications.urls')),
    path('api/', include('apps.files.urls')),
    path('api/', include('apps.forms.urls')),
    path('api/', include('apps.summaries.urls')),
    path('api/', include('apps.knowledge.urls')),
]
