from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

from reports.sitemaps import StaticViewSitemap, StorySitemap

_sitemaps = {
    "static": StaticViewSitemap,
    "stories": StorySitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('reports.urls')),
    path('account/', include('account.urls', namespace='account')),
    path('accounts/', include('django.contrib.auth.urls')),  # ✨ wichtig für login/logout
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": _sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path(
        "robots.txt",
        TemplateView.as_view(template_name="robots.txt", content_type="text/plain"),
        name="robots_txt",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
