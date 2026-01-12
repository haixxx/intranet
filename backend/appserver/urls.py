from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),

    # i18n: cung cấp route 'set_language'
    path('i18n/', include('django.conf.urls.i18n')),

    path('auth/', include(('apps.core.urls', 'core'), namespace='core')),
    path('backoffice/', include(('apps.backoffice.urls', 'backoffice'), namespace='backoffice')),

    # NEW: Ingest API for attendance devices (Windows client pushes batches here)
    path('', include(('apps.attendance_devices.urls', 'attendance_devices'), namespace='attendance_devices')),

    # Default redirect to dashboard
    path('', RedirectView.as_view(pattern_name='backoffice:dashboard', permanent=False)),
]