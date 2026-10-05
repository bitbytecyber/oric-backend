"""
Response envelope renderer + exception handler (same contract as sis_backend):

    success: {"ok": true,  "data": ..., "meta": {"request_id": ...}}
    error:   {"ok": false, "error", "code", "message", "details", "meta"}

Difference from sis_backend: this is a greenfield API, so the envelope is ON by
default and a view opts *out* with ``envelope = False`` (e.g. file downloads).
"""
from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.renderers import JSONRenderer
from rest_framework.views import exception_handler as drf_exception_handler

ERROR_BY_STATUS = {
    400: ("VALIDATION_ERROR", "Invalid request."),
    401: ("UNAUTHENTICATED", "Authentication required."),
    403: ("FORBIDDEN", "You do not have permission to perform this action."),
    404: ("NOT_FOUND", "Resource not found."),
    405: ("METHOD_NOT_ALLOWED", "Method not allowed."),
    409: ("CONFLICT", "Request conflicts with current state."),
    413: ("PAYLOAD_TOO_LARGE", "Payload too large."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Unsupported media type."),
    422: ("BUSINESS_RULE", "Business rule violation."),
    429: ("THROTTLED", "Too many requests."),
    500: ("SERVER_ERROR", "Server error."),
}


def _request_id(context: dict[str, Any] | None) -> str:
    request = (context or {}).get("request")
    return getattr(request, "request_id", None) or uuid.uuid4().hex


def _is_enveloped(data: Any) -> bool:
    return isinstance(data, dict) and "ok" in data and ("data" in data or "error" in data)


def _wants_envelope(context: dict[str, Any] | None) -> bool:
    view = (context or {}).get("view")
    return view is not None and getattr(view, "envelope", True) is not False


class EnvelopeJSONRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        if _is_enveloped(data) or not _wants_envelope(renderer_context):
            return super().render(data, accepted_media_type, renderer_context)
        response = (renderer_context or {}).get("response")
        status_code = getattr(response, "status_code", 200)
        rid = _request_id(renderer_context)
        if 200 <= status_code < 300:
            payload = {"ok": True, "data": data, "meta": {"request_id": rid}}
        else:
            error, message = ERROR_BY_STATUS.get(status_code, ("ERROR", "An error occurred."))
            payload = {"ok": False, "error": error, "code": error, "message": message, "details": data,
                       "meta": {"request_id": rid}}
        return super().render(payload, accepted_media_type, renderer_context)


def _flatten(detail: Any) -> str:
    if isinstance(detail, list) and detail:
        return _flatten(detail[0])
    if isinstance(detail, dict) and detail:
        key, value = next(iter(detail.items()))
        msg = _flatten(value)
        return msg if key in ("non_field_errors", "detail") else f"{key}: {msg}"
    return str(detail)


def _serialize(detail: Any) -> Any:
    if isinstance(detail, dict):
        return {k: _serialize(v) for k, v in detail.items()}
    if isinstance(detail, list):
        return [_serialize(v) for v in detail]
    return str(detail)


def envelope_exception_handler(exc: Exception, context: dict[str, Any]):
    if isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied(str(exc) or None)
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    response = drf_exception_handler(exc, context)
    if response is None or not _wants_envelope(context):
        return response

    from oric_backend.errors import DomainAPIError

    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        # Session auth has no WWW-Authenticate header so DRF answers 403; the SPA
        # needs to tell "signed out" (401) from "not allowed" (403).
        response.status_code = 401
    status_code = response.status_code
    error, message = ERROR_BY_STATUS.get(status_code, ("ERROR", "An error occurred."))
    code, details = error, None
    if isinstance(exc, DomainAPIError):
        code, error, message, details = exc.code, exc.error_name, exc.message, exc.details
    elif isinstance(exc, exceptions.ValidationError):
        message = _flatten(exc.detail) or message
        details = _serialize(exc.detail)
    elif isinstance(exc, exceptions.APIException) and getattr(exc, "detail", None):
        message = str(exc.detail)
    response.data = {
        "ok": False,
        "error": error,
        "code": code,
        "message": message,
        "details": details,
        "meta": {"request_id": _request_id(context)},
    }
    return response
