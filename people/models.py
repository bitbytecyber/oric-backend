"""Identity, mirroring sis_backend/people/models.py.

``User`` is the authentication account (django-allauth, email login, auto-generated
username). ``Person`` is the canonical human identity and profile (name, photo,
designation, department …), one-to-one with ``User``. Code that only *reads* profile
fields can use the ``User`` convenience properties; writes go through ``Person``.
"""
import secrets

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from mixins import BaseModelMixin


class UserManager(BaseUserManager):
    """Email is the unique identifier for authentication (same as sis_backend)."""

    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("The Email must be set"))
        email = self.normalize_email(email).lower()
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("username", f"usr_{secrets.token_hex(8)}")
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_staff=True and is_superuser=True."))
        return self.create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(models.Q(**{self.model.USERNAME_FIELD: username}) | models.Q(email__iexact=username))


class User(AbstractUser, BaseModelMixin):
    # allauth still validates a username even with email login; it is generated, never shown.
    username = models.CharField(_("username"), max_length=150)
    email = models.EmailField(_("Email"), unique=True)
    must_change_password = models.BooleanField(
        default=False, help_text=_("Set when an administrator chooses the password; cleared on first change.")
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["first_name", "last_name", "email"]

    def __str__(self):
        return f"{self.id} - {self.email}"

    # ---- read-through profile helpers (Person is the source of truth) ---------
    def _person(self):
        try:
            return self.person
        except Person.DoesNotExist:
            return None

    @property
    def full_name(self) -> str:
        p = self._person()
        if p and p.full_name:
            return p.full_name
        return " ".join(x for x in (self.first_name, self.last_name) if x).strip() or self.email

    @property
    def designation(self) -> str:
        p = self._person()
        return p.designation if p else ""

    @property
    def department(self):
        p = self._person()
        return p.department if p else None

    @property
    def department_id(self):
        p = self._person()
        return p.department_id if p else None

    def get_full_name(self):
        return self.full_name


class Person(BaseModelMixin):
    """Canonical identity + ORIC profile of a faculty member / staff person."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="person", null=True, blank=True
    )
    full_name = models.CharField(_("full name"), max_length=255, blank=True,
                                 help_text=_("As printed on returns, with title, e.g. Dr. Ayesha Khan."))
    avatar = models.ImageField(_("profile picture"), upload_to="people/avatars/", blank=True, null=True)
    designation = models.CharField(_("designation"), max_length=120, blank=True, help_text=_("e.g. Associate Professor"))
    department = models.ForeignKey("org.Department", null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="members")
    employee_id = models.CharField(_("employee ID"), max_length=40, blank=True)
    phone = models.CharField(_("phone"), max_length=30, blank=True)
    office = models.CharField(_("office / extension"), max_length=120, blank=True)
    orcid = models.CharField(_("ORCID iD"), max_length=19, blank=True, help_text=_("0000-0000-0000-0000"))
    google_scholar = models.URLField(_("Google Scholar profile"), blank=True)
    research_interests = models.TextField(_("research interests"), blank=True)
    bio = models.TextField(_("short bio"), blank=True)

    class Meta:
        verbose_name = _("person")
        verbose_name_plural = _("people")
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name or (self.user.email if self.user_id else f"Person {self.pk}")


class SocialAccountStatus(BaseModelMixin):
    """Admin switch for ONE linked sign-in identity (e.g. a Google account), as in sis_backend.

    The reversible alternative to disconnecting: a deactivated identity is refused at
    sign-in (people/adapters.py) while the account itself and its password still work.
    """

    social_account = models.OneToOneField("socialaccount.SocialAccount", on_delete=models.CASCADE,
                                          related_name="status")
    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="+")

    class Meta:
        verbose_name = _("social account status")
        verbose_name_plural = _("social account statuses")
