from rest_framework import permissions

from oric_backend.errors import InsufficientPermissionError

from .services.authz_audit import log_authz_denial
from .utils import user_has_capability


def _resolve_department_id(request, view) -> int | None:
    field = getattr(view, "department_param", None)
    if not field:
        return None
    for source in (getattr(view, "kwargs", {}) or {}, request.query_params, getattr(request, "data", {}) or {}):
        try:
            raw = source.get(field) if hasattr(source, "get") else None
        except Exception:
            raw = None
        if raw not in (None, ""):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None
    return None


class HasCapability(permissions.BasePermission):
    """Require the view's capability key (``required_capability`` or ``get_required_capability``).

    A falsy key means "authenticated is enough"; ``__unmapped__`` denies
    everyone but superusers. Denials are logged and raise a 403 naming the key.
    """

    message = "Missing required capability."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if hasattr(view, "get_required_capability"):
            key = view.get_required_capability(request)
        else:
            key = getattr(view, "required_capability", None)
        if not key:
            return True
        department_id = _resolve_department_id(request, view)
        if user_has_capability(request.user, key, department_id=department_id):
            return True
        log_authz_denial(user=request.user, capability_key=key, path=request.path, method=request.method,
                         department_id=department_id)
        raise InsufficientPermissionError(required_permission=key)
