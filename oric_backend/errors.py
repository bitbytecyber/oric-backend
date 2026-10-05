"""Domain exceptions that serialize through the envelope exception handler."""
from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException


class DomainAPIError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Request failed."
    default_code = "ERROR"

    def __init__(self, *, code: str | None = None, message: str | None = None, http_status: int | None = None,
                 error_name: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.code = code or self.default_code
        self.error_name = error_name or self.code
        self.message = message or self.default_detail
        self.details = details
        if http_status is not None:
            self.status_code = http_status
        super().__init__(detail=self.message, code=self.code)


class BusinessRuleError(DomainAPIError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "Business rule violation."
    default_code = "BUSINESS_RULE"


class CycleClosedError(DomainAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This reporting cycle is closed for submissions."
    default_code = "CYCLE_CLOSED"


class SubmissionLockedError(DomainAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This return is locked while it is under review or after a decision."
    default_code = "SUBMISSION_LOCKED"


class InsufficientPermissionError(DomainAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "You do not have permission to perform this action."
    default_code = "INSUFFICIENT_PERMISSION"

    def __init__(self, *, required_permission: str, message: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            code=self.default_code,
            error_name="FORBIDDEN",
            message=message or self.default_detail,
            details={"required_permission": required_permission},
            **kwargs,
        )


class PrivilegeEscalationError(DomainAPIError):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "You cannot grant a capability you do not hold yourself."
    default_code = "PRIVILEGE_ESCALATION"


class SelfLockoutError(DomainAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This change would remove your own access to role management."
    default_code = "SELF_LOCKOUT"


class SystemRoleProtectedError(DomainAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "System roles cannot be renamed or deleted."
    default_code = "SYSTEM_ROLE_PROTECTED"
