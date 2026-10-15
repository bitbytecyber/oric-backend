from rest_framework import serializers

from .models import ContactMessage, Department, Faculty, Organization, ReportingCycle, TeamMember


class PersonMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    designation = serializers.CharField()
    email = serializers.CharField(source="user.email", default=None)


class FacultySerializer(serializers.ModelSerializer):
    dean_detail = PersonMiniSerializer(source="dean", read_only=True)
    department_count = serializers.IntegerField(read_only=True, required=False)
    member_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Faculty
        fields = ["id", "code", "name", "short_name", "dean", "dean_detail", "order", "is_active",
                  "department_count", "member_count"]


class DepartmentSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True, required=False)
    faculty_code = serializers.CharField(source="faculty.code", read_only=True, default=None)
    faculty_name = serializers.CharField(source="faculty.name", read_only=True, default=None)
    chair_detail = PersonMiniSerializer(source="chair", read_only=True)
    co_chairs_detail = PersonMiniSerializer(source="co_chairs", many=True, read_only=True)

    class Meta:
        model = Department
        fields = ["id", "name", "code", "faculty", "faculty_code", "faculty_name", "chair", "chair_detail",
                  "co_chairs", "co_chairs_detail", "website", "is_active", "member_count"]


class OrganizationSerializer(serializers.ModelSerializer):
    submission_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Organization
        fields = ["id", "name", "kind", "country", "aliases", "submission_count"]


class ReportingCycleSerializer(serializers.ModelSerializer):
    accepts_submissions = serializers.BooleanField(read_only=True)

    class Meta:
        model = ReportingCycle
        fields = ["id", "label", "year", "starts_on", "ends_on", "submission_deadline", "status", "notes",
                  "accepts_submissions", "phd_faculty_count", "sanctioned_faculty_posts", "existing_faculty_count"]

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
