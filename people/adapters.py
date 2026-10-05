"""django-allauth adapters (sis_backend people/adapters.py pattern, ORIC-sized).

* Signup is CLOSED: ORIC provisions accounts (People admin / seeders).
* Inactive-account sign-in attempts are recorded in the audit trail.
* Google sign-in (social adapter): verified email only, auto-link to the existing
  ORIC account with that email, never create accounts, never reactivate a disabled
  one, never change roles; an admin can switch one linked identity off.
* The headless session payload carries our profile shape, so the SPA gets the
  user + profile in one call to ``/_allauth/browser/v1/auth/session``.
"""
import logging
import secrets

from allauth.account.adapter import DefaultAccountAdapter
from allauth.headless.adapter import DefaultHeadlessAdapter
from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger("authentication.security")


class ORICAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request) -> bool:
        # The legacy portal had no self-registration either; ORIC creates accounts.
        return False

    def save_user(self, request, user, form, commit=True):
        if not user.username:
            user.username = f"usr_{secrets.token_hex(8)}"
        user = super().save_user(request, user, form, commit=commit)
        from people.services.profile import ensure_person_for_user

        ensure_person_for_user(user)
        return user

    def pre_login(self, request, user, **kwargs):
        if not user.is_active:
            from audit.models import ActivityAction
            from audit.services import record_activity

            record_activity(ActivityAction.LOGIN_FAILED, request=request, actor=user,
                            description="Sign-in refused: account deactivated",
                            metadata={"failure_reason": "inactive_account"})
            logger.warning("login attempted on inactive account %s", user.email)
        return super().pre_login(request, user, **kwargs)

    def send_mail(self, template_prefix, email, context):
        context.setdefault("site_name", "NED ORIC Data Portal")
        return super().send_mail(template_prefix, email, context)


class ORICHeadlessAdapter(DefaultHeadlessAdapter):
    def serialize_user(self, user):
        from people.serializers import MeSerializer

        return MeSerializer(user, context={"request": self.request}).data


class ORICMFAAdapter(DefaultMFAAdapter):
    def get_totp_issuer(self) -> str:
        return settings.MFA_TOTP_ISSUER


def _log_social_refusal(request, *, provider: str, reason: str, email: str = "", user=None) -> None:
    """allauth's headless views swallow these refusals before any auth signal fires,
    so record them here (sis_backend _log_social_refusal)."""
    from audit.models import ActivityAction
    from audit.services import record_activity

    record_activity(ActivityAction.LOGIN_FAILED, request=request, actor=user,
                    description=f"{provider.title()} sign-in refused: {reason}",
                    metadata={"provider": provider, "failure_reason": reason, "email": email})
    logger.warning("social login refused provider=%s reason=%s email=%s", provider, reason, email)


def _verified_email(request, sociallogin) -> str:
    """Lower-cased email iff Google asserts it is verified (string or bool claim)."""
    extra = sociallogin.account.extra_data or {}
    email = (sociallogin.user.email or extra.get("email") or "").strip().lower()
    verified = extra.get("email_verified", extra.get("verified_email", False))
    if isinstance(verified, str):
        verified = verified.strip().lower() == "true"
    if not email or not verified:
        _log_social_refusal(request, provider=sociallogin.account.provider, reason="unverified_email", email=email)
        name = sociallogin.account.provider.title()
        raise DjangoValidationError(_("Your %(p)s account email is not verified.") % {"p": name}, code="email_not_verified")
    return email


class ORICSocialAccountAdapter(DefaultSocialAccountAdapter):
    # Raised via self.validation_error() → a *Django* ValidationError, which allauth's
    # headless views turn into a 400 envelope (a DRF error would 500 them).
    error_messages = {
        **DefaultSocialAccountAdapter.error_messages,
        "identity_disabled": _("This sign-in method has been turned off by ORIC. Use your password instead."),
        "account_disabled": _("This account is disabled."),
        "no_account": _("There's no ORIC portal account for this email address. Ask ORIC to create one, "
                        "or sign in with the email ORIC has on file."),
        "domain_not_allowed": _("Use your NED university Google account to sign in."),
        # Apple "Hide My Email" relay addresses never match an ORIC account.
        "apple_relay_email": _("Apple hid your email address, so we can't match it to your ORIC account. "
                               "Sign in with your password, then connect Apple from your profile."),
    }

    def is_open_for_signup(self, request, sociallogin) -> bool:
        # ORIC provisions accounts; Google only signs existing people in.
        return False

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        provider_id = getattr(provider, "id", None) or str(provider or "")
        _log_social_refusal(request, provider=provider_id or "social", reason="provider_error")
        return super().on_authentication_error(request, provider, error=error, exception=exception,
                                               extra_context=extra_context)

    def get_connect_redirect_url(self, request, socialaccount):
        return f"{settings.FRONTEND_URL.rstrip('/')}/profile?tab=security"

    def pre_social_login(self, request, sociallogin):
        provider = sociallogin.account.provider
        account = sociallogin.account
        # An admin may have switched this identity off — checked before every branch,
        # including `connect`, so re-connecting can't quietly revive it.
        if account.pk:
            status = getattr(account, "status", None)
            if status is not None and not status.is_active:
                _log_social_refusal(request, provider=provider, reason="identity_disabled", user=account.user)
                raise self.validation_error("identity_disabled")

        if sociallogin.is_existing:
            if not account.user.is_active:
                _log_social_refusal(request, provider=provider, reason="account_disabled", user=account.user)
                raise self.validation_error("account_disabled")
            return

        # Apple asserts email/email_verified only on the FIRST authorization; returning Apple
        # users are `is_existing` above, so this read only runs for a first link (sis_backend note).
        email = _verified_email(request, sociallogin)
        allowed = getattr(settings, "GOOGLE_ALLOWED_DOMAINS", [])
        if provider == "google" and allowed and email.rsplit("@", 1)[-1] not in allowed:
            _log_social_refusal(request, provider=provider, reason="domain_not_allowed", email=email)
            raise self.validation_error("domain_not_allowed")

        # Connecting from Profile → Sign-in & security: attach to request.user as-is.
        if (sociallogin.state or {}).get("process") == "connect":
            return

        existing = get_user_model().objects.filter(email__iexact=email).first()
        if existing is None and email.endswith("@privaterelay.appleid.com"):
            _log_social_refusal(request, provider=provider, reason="apple_relay_email", email=email)
            raise self.validation_error("apple_relay_email")
        if existing is None:
            _log_social_refusal(request, provider=provider, reason="no_account", email=email)
            raise self.validation_error("no_account")
        if not existing.is_active:
            _log_social_refusal(request, provider=provider, reason="account_disabled", email=email, user=existing)
            raise self.validation_error("account_disabled")

        from people.services.profile import ensure_person_for_user

        ensure_person_for_user(existing)
        # Attach the Google identity to the ORIC account; roles/staff flags untouched.
        sociallogin.connect(request, existing)

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        user.email = (user.email or data.get("email") or "").lower()
        user.username = f"usr_{secrets.token_hex(8)}"
        return user
