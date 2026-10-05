"""Per-request correlation id, shared by auditlog rows and ActivityEvent rows."""
import contextvars

_request_cid: contextvars.ContextVar[str | None] = contextvars.ContextVar("oric_request_cid", default=None)


def set_request_cid(value: str | None):
    return _request_cid.set(value)


def reset_request_cid(token) -> None:
    _request_cid.reset(token)


def get_request_cid() -> str | None:
    return _request_cid.get()
