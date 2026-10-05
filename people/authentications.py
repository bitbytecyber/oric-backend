from django.conf import settings
from django.core.cache import cache
from rest_framework.authentication import SessionAuthentication


def _should_touch(session_key: str | None) -> bool:
    """Renew the sliding expiry at most once per SESSION_TOUCH_INTERVAL per session."""
    if not session_key:
        return False
    return cache.add(f"session-touch:{session_key}", 1, timeout=settings.SESSION_TOUCH_INTERVAL)


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """Session-cookie auth for the SPA, same as sis_backend.

    CSRF is not enforced: the session cookie is SameSite=Lax and the API only
    accepts JSON / multipart from the CORS-allowlisted frontend origin. Idle
    expiry slides (SESSION_COOKIE_AGE) so people are not logged out mid-form.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            session = request._request.session
            if _should_touch(session.session_key):
                session.modified = True
        return result

    def enforce_csrf(self, request):
        return
