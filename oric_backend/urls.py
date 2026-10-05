from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

API = "api/v1/"

urlpatterns = [
    path("admin/", admin.site.urls),
    # django-allauth: headless API for the SPA (/_allauth/browser/v1/…), as in sis_backend.
    path("accounts/", include("allauth.urls")),
    path("_allauth/", include("allauth.headless.urls")),
    path(API, include("people.urls")),
    path(API, include("org.urls")),
    path(API, include("rbac.urls")),
    path(API, include("submissions.urls")),
    path(API, include("reports.urls")),
    path(API, include("notifications.urls")),
    path(API, include("audit.urls")),
]

if settings.SERVE_API_DOCS:
    from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
        path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    ]

# Note: /media is NOT served publicly. Evidence files go through the
# permission-checked download endpoint (legacy served /Uploads/<guid> openly).
# Only non-sensitive photos are exposed: ORIC team photos and profile pictures.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL + "team/", document_root=settings.MEDIA_ROOT / "team")
    urlpatterns += static(settings.MEDIA_URL + "people/avatars/", document_root=settings.MEDIA_ROOT / "people" / "avatars")
