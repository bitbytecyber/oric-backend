from rest_framework import serializers

from .models import ContactMessage, Department, ReportingCycle, TeamMember


class DepartmentSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Department
        fields = ["id", "name", "code", "faculty", "is_active", "member_count"]


class ReportingCycleSerializer(serializers.ModelSerializer):
    accepts_submissions = serializers.BooleanField(read_only=True)

    class Meta:
        model = ReportingCycle
        fields = ["id", "label", "year", "starts_on", "ends_on", "submission_deadline", "status", "notes",
                  "accepts_submissions"]

    def validate(self, attrs):
        s = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        e = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if s and e and e <= s:
            raise serializers.ValidationError({"ends_on": "Must be after the start date."})
        return attrs


class TeamMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamMember
        fields = ["id", "name", "title", "email", "photo", "order", "is_active"]


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["id", "name", "email", "subject", "message", "created_at", "handled", "handled_by"]
        read_only_fields = ["created_at", "handled_by"]


class ContactCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message"]
