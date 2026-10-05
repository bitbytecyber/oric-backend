"""Person helpers (sis_backend people/services/profile.py pattern)."""
from __future__ import annotations

from allauth.account.models import EmailAddress


def ensure_person_for_user(user):
    from people.models import Person

    person, _ = Person.objects.get_or_create(user=user, defaults={"full_name": user.full_name or ""})
    return person


def provision_user(*, email: str, full_name: str, password: str | None = None, designation: str = "",
                   department=None, employee_id: str = "", phone: str = "", is_staff: bool = False,
                   is_superuser: bool = False, must_change_password: bool | None = None, verified: bool = True):
    """Create (or update) an ORIC-provisioned account: User + Person + verified primary EmailAddress.

    Accounts are created by ORIC (signup is closed), so the address is marked verified —
    allauth's mandatory email verification then never blocks a provisioned user.
    """
    from people.models import Person, User

    email = email.strip().lower()
    first, _, last = full_name.replace("Dr. ", "").replace("Engr. ", "").partition(" ")
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User.objects.create_user(email=email, password=password, first_name=first[:150], last_name=last[:150],
                                        is_staff=is_staff, is_superuser=is_superuser)
        if must_change_password is None:
            must_change_password = bool(password)
    else:
        if password:
            user.set_password(password)
        user.first_name, user.last_name = first[:150], last[:150]
        user.is_staff = user.is_staff or is_staff
        user.is_superuser = user.is_superuser or is_superuser
    if must_change_password is not None:
        user.must_change_password = must_change_password
    user.save()
    Person.objects.update_or_create(
        user=user,
        defaults={"full_name": full_name, "designation": designation, "department": department,
                  "employee_id": employee_id, "phone": phone},
    )
    EmailAddress.objects.update_or_create(
        user=user, email=email, defaults={"verified": verified, "primary": True}
    )
    return user
