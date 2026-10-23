"""
    URL configuration for project.
"""

from django.conf.urls.static import static
from django.conf import settings
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),

    # path('', include('pwa.urls')),

    path('a/', include('apps.account.urls', namespace='account')),
    path('ai/', include('apps.ai_assistant.urls', namespace='ai_assistant')),
    path('', include('apps.public.urls', namespace='public')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
