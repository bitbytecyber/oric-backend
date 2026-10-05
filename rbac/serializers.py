from rest_framework import serializers

from submissions.registry import PILLAR_BY_KEY

from .models import AccessRole, Capability, RoleAssignment


class CapabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Capability
        fields = ["key", "name", "description", "module", "resource", "action", "is_dangerous"]


class AccessRoleSerializer(serializers.ModelSerializer):
    capability_count = serializers.IntegerField(read_only=True)
    assignment_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AccessRole
        fields = ["id", "slug", "name", "description", "is_system", "pillars", "capability_count",
                  "assignment_count", "created_at", "updated_at"]
        read_only_fields = ["is_system", "created_at", "updated_at"]

    def validate_pillars(self, value):
        bad = [p for p in value or [] if p not in PILLAR_BY_KEY]
        if bad:
            raise serializers.ValidationError(f"Unknown pillar(s): {', '.join(bad)}")
        return sorted(set(value or []))


class RoleCapabilitiesSerializer(serializers.Serializer):
    capability_keys = serializers.ListField(child=serializers.CharField(), allow_empty=True)


class RoleAssignmentSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_slug = serializers.CharField(source="role.slug", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    granted_by_email = serializers.EmailField(source="granted_by.email", read_only=True, default=None)

    class Meta:
        model = RoleAssignment
        fields = ["id", "user", "user_email", "user_name", "role", "role_name", "role_slug", "department",
                  "department_name", "is_active", "note", "granted_by", "granted_by_email", "created_at"]
        read_only_fields = ["granted_by", "created_at"]
