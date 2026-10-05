from rest_framework import serializers

from .access import can_delete, can_edit
from .models import EvidenceFile, ReviewEvent, SectionEntry, Submission
from .services import allowed_actions


class EvidenceFileSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = EvidenceFile
        fields = ["id", "field", "original_name", "size", "content_type", "uploaded_at", "download_url"]

    def get_download_url(self, obj):
        return f"/api/v1/evidence/{obj.pk}/download/"


class SectionEntrySerializer(serializers.ModelSerializer):
    files = EvidenceFileSerializer(many=True, read_only=True)

    class Meta:
        model = SectionEntry
        fields = ["id", "submission", "section", "data", "files", "created_at", "updated_at"]
        read_only_fields = ["submission", "section", "data", "created_at", "updated_at"]


class ReviewEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True, default=None)

    class Meta:
        model = ReviewEvent
        fields = ["id", "action", "from_status", "to_status", "comment", "actor", "actor_name", "created_at"]


class SubmissionListSerializer(serializers.ModelSerializer):
    pillar_name = serializers.CharField(source="get_pillar_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    cycle_label = serializers.CharField(source="cycle.label", read_only=True)
    year = serializers.IntegerField(source="cycle.year", read_only=True)
    entry_count = serializers.IntegerField(read_only=True, default=0)
    declared_total = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ["id", "pillar", "pillar_name", "cycle", "cycle_label", "year", "owner", "faculty_name",
                  "faculty_email", "designation", "department", "department_name", "status", "status_label",
                  "submitted_at", "reviewed_at", "created_at", "updated_at", "entry_count", "declared_total"]

    def get_declared_total(self, obj):
        return sum(int(v or 0) for v in (obj.counts or {}).values())


class SubmissionDetailSerializer(SubmissionListSerializer):
    entries = SectionEntrySerializer(many=True, read_only=True)
    events = ReviewEventSerializer(many=True, read_only=True)
    progress = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    reviewed_by_name = serializers.CharField(source="reviewed_by.full_name", read_only=True, default=None)

    class Meta(SubmissionListSerializer.Meta):
        fields = SubmissionListSerializer.Meta.fields + [
            "counts", "review_comment", "reviewed_by", "reviewed_by_name", "entries", "events", "progress",
            "permissions",
        ]

    def get_progress(self, obj):
        return obj.entry_progress()

    def get_permissions(self, obj):
        user = self.context["request"].user
        return {
            "can_edit": can_edit(user, obj),
            "can_delete": can_delete(user, obj),
            "actions": allowed_actions(user, obj),
        }


class SubmissionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submission
        fields = ["id", "pillar", "cycle", "department", "faculty_name", "faculty_email", "designation", "counts"]
        extra_kwargs = {
            "cycle": {"required": False},
            "department": {"required": False},
            "faculty_name": {"required": False},
            "faculty_email": {"required": False},
            "counts": {"required": False},
        }


class SubmissionUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submission
        fields = ["department", "faculty_name", "faculty_email", "designation", "counts"]


class TransitionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ReviewEvent.Action.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="")
