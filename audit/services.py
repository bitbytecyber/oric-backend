import logging

from django.contrib.contenttypes.models import ContentType

from .cid import get_request_cid
from .models import ActivityAction, ActivityEvent

logger = logging.getLogger("oric")


def _client_ip(request):
    if request is None:
        return None
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


def record_activity(action: str, *, request=None, actor=None, target=None, description: str = "",
                    metadata: dict | None = None) -> None:
    """Write an ActivityEvent. Never raises: auditing must not break the request."""
    try:
        if actor is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
            actor = request.user
        ActivityEvent.objects.create(
            action=action,
            actor=actor if actor is not None and getattr(actor, "pk", None) else None,
            actor_label=(getattr(actor, "email", "") or "") if actor is not None else "",
            description=description[:500],
            target_type=ContentType.objects.get_for_model(target) if target is not None else None,
            target_id=str(getattr(target, "pk", "") or "") if target is not None else "",
            request_id=getattr(request, "request_id", None) or get_request_cid() or "",
            path=(request.path[:500] if request is not None else ""),
            method=(request.method if request is not None else ""),
            remote_addr=_client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:500] if request is not None else ""),
            metadata=metadata or {},
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("record_activity failed (%s)", action)


def record_export(request, *, description: str, count: int | None = None) -> None:
    record_activity(ActivityAction.EXPORT, request=request, description=description, metadata={"count": count})
