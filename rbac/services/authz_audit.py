import logging

logger = logging.getLogger("authentication.security")


def log_authz_denial(*, user, capability_key: str, path: str = "", method: str = "",
                     department_id: int | None = None) -> None:
    from rbac.models import AuthzDenialLog

    try:
        AuthzDenialLog.objects.create(
            user=user if getattr(user, "pk", None) else None,
            capability_key=capability_key[:64],
            path=path[:500],
            method=method[:10],
            department_id=department_id,
        )
    except Exception:  # pragma: no cover - never break the request for logging
        logger.exception("could not persist authz denial")
    logger.info("authz denied user=%s key=%s %s %s dept=%s", getattr(user, "pk", None), capability_key, method,
                path, department_id)
