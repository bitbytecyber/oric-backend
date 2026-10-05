from rest_framework import serializers

from org.models import Department

from .models import Person, User


def _abs(request, f):
    if not f:
        return None
    url = f.url
    return request.build_absolute_uri(url) if request is not None else url


class MeSerializer(serializers.ModelSerializer):
    """Signed-in user + profile. Also the allauth headless ``user`` payload."""

    full_name = serializers.CharField(read_only=True)
    designation = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    employee_id = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    has_usable_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "first_name", "last_name", "designation", "department",
                  "department_name", "employee_id", "phone", "avatar", "is_superuser", "must_change_password",
                  "has_usable_password", "last_login", "date_joined"]

    def _p(self, obj) -> Person | None:
        return getattr(obj, "person", None) if hasattr(obj, "person") else None

    def get_designation(self, obj):
        return obj.designation

    def get_department(self, obj):
        return obj.department_id

    def get_department_name(self, obj):
        return obj.department.name if obj.department else None

    def get_employee_id(self, obj):
        p = self._p(obj)
        return p.employee_id if p else ""

    def get_phone(self, obj):
        p = self._p(obj)
        return p.phone if p else ""

    def get_avatar(self, obj):
        p = self._p(obj)
        return _abs(self.context.get("request"), p.avatar) if p and p.avatar else None

    def get_has_usable_password(self, obj):
        return obj.has_usable_password()


class ProfileSerializer(serializers.ModelSerializer):
    """GET/PATCH /me/profile/ — the Person record (sis_backend ProfileMe pattern)."""

    email = serializers.EmailField(source="user.email", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    avatar = serializers.ImageField(required=False, allow_null=True)
    remove_avatar = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Person
        fields = ["full_name", "email", "designation", "department", "department_name", "employee_id", "phone",
                  "office", "orcid", "google_scholar", "research_interests", "bio", "avatar", "remove_avatar"]
        # Department and employee ID are institutional records: ORIC changes them, not the user.
        read_only_fields = ["department", "employee_id"]

    def validate_full_name(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Enter your full name as it should appear on returns.")
        return value

    def validate_orcid(self, value):
        import re

        if value and not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", value):
            raise serializers.ValidationError("Use the format 0000-0000-0000-0000.")
        return value

    def validate_avatar(self, f):
        if f and f.size > 2 * 1024 * 1024:
            raise serializers.ValidationError("Profile pictures must be under 2 MB.")
        return f

    def update(self, instance, validated_data):
        if validated_data.pop("remove_avatar", False):
            instance.avatar = None
        person = super().update(instance, validated_data)
        user = person.user
        first, _, last = person.full_name.replace("Dr. ", "").replace("Engr. ", "").partition(" ")
        if user and (user.first_name, user.last_name) != (first[:150], last[:150]):
            user.first_name, user.last_name = first[:150], last[:150]
            user.save(update_fields=["first_name", "last_name", "updated_at"])
        return person

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["avatar"] = _abs(self.context.get("request"), instance.avatar) if instance.avatar else None
        return data


class UserAdminSerializer(serializers.ModelSerializer):
    """People admin: account + profile in one flat shape."""

    full_name = serializers.CharField()
    designation = serializers.CharField(required=False, allow_blank=True)
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), required=False, allow_null=True)
    department_name = serializers.SerializerMethodField()
    employee_id = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    roles = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "designation", "department", "department_name", "employee_id",
                  "phone", "is_active", "is_superuser", "last_login", "date_joined", "roles", "password"]
        read_only_fields = ["id", "is_superuser", "last_login", "date_joined"]

    def get_department_name(self, obj):
        return obj.department.name if obj.department else None

    def get_roles(self, obj):
        return [
            {"slug": a.role.slug, "name": a.role.name, "department_id": a.department_id}
            for a in obj.role_assignments.all()
            if a.is_active
        ]

    def to_representation(self, obj):
        data = super().to_representation(obj)
        p = getattr(obj, "person", None)
        data.update({
            "full_name": obj.full_name,
            "designation": p.designation if p else "",
            "department": p.department_id if p else None,
            "employee_id": p.employee_id if p else "",
            "phone": p.phone if p else "",
        })
        return data

    def validate_email(self, value):
        value = value.lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Someone already has this email address.")
        return value

    def create(self, validated_data):
        from django.contrib.auth import password_validation

        from people.services.profile import provision_user

        password = validated_data.pop("password", "") or None
        if password:
            password_validation.validate_password(password)
        return provision_user(
            email=validated_data["email"], full_name=validated_data["full_name"], password=password,
            designation=validated_data.get("designation", ""), department=validated_data.get("department"),
            employee_id=validated_data.get("employee_id", ""), phone=validated_data.get("phone", ""),
        )

    def update(self, instance, validated_data):
        from people.services.profile import ensure_person_for_user

        validated_data.pop("password", None)  # use the set_password action
        person = ensure_person_for_user(instance)
        for f in ("full_name", "designation", "department", "employee_id", "phone"):
            if f in validated_data:
                setattr(person, f, validated_data.pop(f))
        person.save()
        if "email" in validated_data and validated_data["email"] != instance.email:
            from allauth.account.models import EmailAddress

            EmailAddress.objects.filter(user=instance).delete()
            EmailAddress.objects.create(user=instance, email=validated_data["email"], verified=True, primary=True)
        if "is_active" in validated_data:
            instance.is_active = validated_data["is_active"]
        if "email" in validated_data:
            instance.email = validated_data["email"]
        instance.save()
        return instance
