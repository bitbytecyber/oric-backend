from rest_framework import serializers

from .access import can_delete, can_edit
from .models import Contributor, EvidenceFile, ReviewEvent, SavedView, Submission
from .services import allowed_actions


class EvidenceFileSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = EvidenceFile
        fields = ["id", "field", "original_name", "size", "content_type", "uploaded_at", "download_url"]

    def get_download_url(self, obj):
        return f"/api/v1/evidence/{obj.pk}/download/"


class ContributorSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    person_email = serializers.CharField(source="person.user.email", read_only=True, default=None)
    department_code = serializers.CharField(source="person.department.code", read_only=True, default=None)
    person_designation = serializers.CharField(source="person.designation", read_only=True, default=None)

    class Meta:
        model = Contributor
        fields = ["id", "role", "person", "name", "designation", "affiliation", "display_name", "person_email",
                  "department_code", "person_designation"]


class ReviewEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True, default=None)

    class Meta:
        model = ReviewEvent
        fields = ["id", "action", "from_status", "to_status", "comment", "actor", "actor_name", "created_at"]


class SubmissionListSerializer(serializers.ModelSerializer):
    category_label = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True, default=None)
    department_code = serializers.CharField(source="department.code", read_only=True, default=None)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    faculty_code = serializers.CharField(source="faculty.code", read_only=True, default=None)
    cycle_label = serializers.CharField(source="cycle.label", read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True, default=None)
    submitted_by_name = serializers.CharField(source="submitted_by.full_name", read_only=True, default=None)
    on_behalf = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ["id", "category", "category_label", "pillar", "cycle", "cycle_label", "title", "event_date",
                  "amount_pkr", "scope_level", "funding_source", "organization", "organization_name", "owner",
                  "owner_name", "department", "department_code", "department_name", "faculty", "faculty_code",
                  "status", "status_label", "source", "needs_match", "submitted_at", "verified_at", "created_at",
                  "updated_at", "submitted_by_name", "on_behalf"]

    def get_category_label(self, obj):
        return obj.category_def["short"]

    def get_on_behalf(self, obj):
        return bool(obj.submitted_by_id and obj.owner_id and obj.owner.user_id != obj.submitted_by_id)


class SubmissionDetailSerializer(SubmissionListSerializer):
    contributors = ContributorSerializer(many=True, read_only=True)
    files = EvidenceFileSerializer(many=True, read_only=True)
    events = ReviewEventSerializer(many=True, read_only=True)
    verified_by_name = serializers.CharField(source="verified_by.full_name", read_only=True, default=None)
    lineage_chain = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta(SubmissionListSerializer.Meta):
        fields = SubmissionListSerializer.Meta.fields + [
            "data", "evidence_links", "review_comment", "verified_by", "verified_by_name", "contributors", "files",
            "events", "lineage", "lineage_chain", "import_ref", "permissions",
        ]

    def get_lineage_chain(self, obj):
        chain, cur, seen = [], obj, set()
        while cur.lineage_id and cur.lineage_id not in seen:
            seen.add(cur.lineage_id)
            cur = cur.lineage
            chain.insert(0, cur)
        chain.append(obj)
        chain += list(obj.next_stages.all())
        return [{"id": s.pk, "category": s.category, "label": s.category_def["short"], "status": s.status,
                 "event_date": s.event_date, "current": s.pk == obj.pk} for s in chain]

    def get_permissions(self, obj):
        user = self.context["request"].user
        return {
            "can_edit": can_edit(user, obj),
            "can_delete": can_delete(user, obj),
            "actions": allowed_actions(user, obj),
            "next_stages": next_stages(user, obj),
        }


def next_stages(user, obj) -> list[str]:
    """A stage advances only once ORIC has verified it (an unverified proposal can't be "approved"),
    and only for its author or staff who can change it. A granted patent has no next stage."""
    from .access import _is_author, can_staff

    if obj.status != "verified":
        return []
    if not (_is_author(user, obj) or can_staff(user, "submission.change", obj)):
        return []
    if obj.category == "patent" and (obj.data or {}).get("filed_or_granted") == "Granted":
        return []
    return obj.category_def["next_stages"]


class SubmissionWriteSerializer(serializers.Serializer):
    category = serializers.CharField()
    cycle = serializers.IntegerField(required=False, allow_null=True)
    owner = serializers.IntegerField(required=False, allow_null=True, help_text="Person id (on behalf of).")
    data = serializers.JSONField(required=False, default=dict)
    people = serializers.JSONField(required=False, default=list)
    submit = serializers.BooleanField(required=False, default=False)


class TransitionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ReviewEvent.Action.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class SavedViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedView
        fields = ["id", "name", "filters", "created_at"]
