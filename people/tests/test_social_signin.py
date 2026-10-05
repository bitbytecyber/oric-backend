"""Google sign-in policy (people/adapters.ORICSocialAccountAdapter), mirroring the
rules sis_backend enforces in SISSocialAccountAdapter.pre_social_login."""
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings

from people.adapters import ORICSocialAccountAdapter
from people.models import SocialAccountStatus, User
from people.services.profile import provision_user


def _login(email, *, verified=True, uid="g-123"):
    user = User(email=email)
    account = SocialAccount(provider="google", uid=uid,
                            extra_data={"email": email, "email_verified": verified, "name": "Test Person"})
    return SocialLogin(user=user, account=account, email_addresses=[])


TEST_PROVIDERS = {
    "google": {"APPS": [{"client_id": "test-client.apps.googleusercontent.com", "secret": "", "key": ""}],
               "SCOPE": ["profile", "email"], "VERIFIED_EMAIL": False},
    "apple": {"APPS": [{"client_id": "pk.test.oric", "secret": "KEYID", "key": "TEAMID",
                        "settings": {"certificate_key": "x"}}], "VERIFIED_EMAIL": False},
}


def _apple(email, *, verified="true", uid="001234.apple"):
    user = User(email=email)
    account = SocialAccount(provider="apple", uid=uid, extra_data={"email": email, "email_verified": verified})
    return SocialLogin(user=user, account=account, email_addresses=[])


@override_settings(SOCIALACCOUNT_PROVIDERS=TEST_PROVIDERS)
class GoogleSignInPolicyTests(TestCase):
    def setUp(self):
        self.adapter = ORICSocialAccountAdapter()
        self.rf = RequestFactory()
        self.request = self.rf.post("/_allauth/browser/v1/auth/provider/token")
        self.request.user = None
        self.user = provision_user(email="ayesha.khan@neduet.edu.pk", full_name="Dr. Ayesha Khan",
                                   password="x-Strong-Pass-1", must_change_password=False)

    def _connected(self, sl):
        # sociallogin.connect() persists the SocialAccount against the matched user.
        return SocialAccount.objects.filter(provider="google", uid=sl.account.uid).first()

    def test_links_to_existing_account_by_verified_email(self):
        sl = _login("Ayesha.Khan@neduet.edu.pk")
        self.adapter.pre_social_login(self.request, sl)
        acc = self._connected(sl)
        self.assertIsNotNone(acc)
        self.assertEqual(acc.user_id, self.user.pk)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)  # never escalates

    def test_unverified_google_email_is_refused(self):
        with self.assertRaises(ValidationError) as cm:
            self.adapter.pre_social_login(self.request, _login(self.user.email, verified="false"))
        self.assertEqual(cm.exception.code, "email_not_verified")

    def test_unknown_address_never_creates_an_account(self):
        with self.assertRaises(ValidationError) as cm:
            self.adapter.pre_social_login(self.request, _login("stranger@gmail.com"))
        self.assertEqual(cm.exception.code, "no_account")
        self.assertFalse(User.objects.filter(email="stranger@gmail.com").exists())
        self.assertFalse(self.adapter.is_open_for_signup(self.request, _login("x@y.z")))

    def test_disabled_account_is_not_reactivated(self):
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(ValidationError) as cm:
            self.adapter.pre_social_login(self.request, _login(self.user.email))
        self.assertEqual(cm.exception.code, "account_disabled")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    @override_settings(GOOGLE_ALLOWED_DOMAINS=["neduet.edu.pk"], SOCIALACCOUNT_PROVIDERS=TEST_PROVIDERS)
    def test_domain_restriction(self):
        provision_user(email="someone@gmail.com", full_name="Someone Else", password="x-Strong-Pass-1")
        with self.assertRaises(ValidationError) as cm:
            self.adapter.pre_social_login(self.request, _login("someone@gmail.com"))
        self.assertEqual(cm.exception.code, "domain_not_allowed")
        self.adapter.pre_social_login(self.request, _login(self.user.email, uid="g-ok"))  # allowed domain passes

    def test_admin_disabled_identity_is_refused(self):
        acc = SocialAccount.objects.create(user=self.user, provider="google", uid="g-999",
                                           extra_data={"email": self.user.email, "email_verified": True})
        SocialAccountStatus.objects.create(social_account=acc, is_active=False)
        sl = _login(self.user.email, uid="g-999")
        sl.account = acc  # allauth's lookup binds the persisted row before calling the adapter
        with self.assertRaises(ValidationError) as cm:
            self.adapter.pre_social_login(self.request, sl)
        self.assertEqual(cm.exception.code, "identity_disabled")


@override_settings(SOCIALACCOUNT_PROVIDERS=TEST_PROVIDERS)
class AppleSignInPolicyTests(TestCase):
    """Apple: same rules, plus its quirks (string `email_verified`, email only on first
    authorization, "Hide My Email" relay addresses)."""

    def setUp(self):
        self.adapter = ORICSocialAccountAdapter()
        self.request = RequestFactory().post("/accounts/apple/login/callback/")
        self.request.user = None
        self.user = provision_user(email="sana.javed@neduet.edu.pk", full_name="Dr. Sana Javed",
                                   password="x-Strong-Pass-1", must_change_password=False)

    def test_first_apple_sign_in_links_by_verified_email(self):
        sl = _apple(self.user.email)
        self.adapter.pre_social_login(self.request, sl)
        acc = SocialAccount.objects.get(provider="apple", uid=sl.account.uid)
        self.assertEqual(acc.user_id, self.user.pk)

    def test_returning_apple_user_needs_no_email(self):
        acc = SocialAccount.objects.create(user=self.user, provider="apple", uid="001234.apple", extra_data={})
        sl = SocialLogin(user=self.user, account=acc, email_addresses=[])  # Apple sends no email the 2nd time
        self.adapter.pre_social_login(self.request, sl)  # must not raise email_not_verified

    def test_hide_my_email_relay_gets_a_helpful_refusal(self):
        with self.assertRaises(ValidationError) as cm:
            self.adapter.pre_social_login(self.request, _apple("x7k2@privaterelay.appleid.com"))
        self.assertEqual(cm.exception.code, "apple_relay_email")

    def test_unverified_apple_email_is_refused(self):
        with self.assertRaises(ValidationError) as cm:
            self.adapter.pre_social_login(self.request, _apple(self.user.email, verified="false"))
        self.assertEqual(cm.exception.code, "email_not_verified")
