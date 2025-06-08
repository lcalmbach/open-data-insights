from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('reports.urls')),
    path('account/', include('account.urls', namespace='account')), 
    path('accounts/', include('django.contrib.auth.urls')),  # ✨ wichtig für login/logout
]