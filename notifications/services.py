"""Single entry point for notifications: in-app row + best-effort email."""
import logging

from django.conf import settings
from django.core.mail import send_mail

from .models import Notification

logger = logging.getLogger("oric")


def notify(user, kind: str, title: str, *, body: str = "", link: str = "", email: bool = True):
    n = Notification.objects.create(user=user, kind=kind, title=title[:200], body=body, link=link)
    if email and user.email:
        try:
            url = f"{settings.FRONTEND_URL}{link}" if link else settings.FRONTEND_URL
            send_mail(title, f"{body}\n\nOpen: {url}\n\nORIC, NED University".strip(), settings.DEFAULT_FROM_EMAIL,
                      [user.email], fail_silently=True)
        except Exception:  # pragma: no cover
            logger.exception("notification email failed")
    return n
