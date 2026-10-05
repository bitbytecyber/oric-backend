import re
import uuid

from .cid import reset_request_cid, set_request_cid

_SAFE_ID = re.compile(r"^[A-Za-z0-9\-_.]{8,64}$")


class RequestIdMiddleware:
    """Mint (or accept a well-formed inbound) X-Request-Id; expose it on request + response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        inbound = request.headers.get("X-Request-Id", "")
        rid = inbound if _SAFE_ID.match(inbound or "") else uuid.uuid4().hex
        request.request_id = rid
        token = set_request_cid(rid)
        try:
            response = self.get_response(request)
        finally:
            reset_request_cid(token)
        response["X-Request-Id"] = rid
        return response
