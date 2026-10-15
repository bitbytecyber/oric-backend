from django.contrib import admin

from .models import Contributor, EvidenceFile, ReviewEvent, SavedView, Submission


class ContributorInline(admin.TabularInline):
    model = Contributor
    extra = 0
    raw_id_fields = ["person"]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["id", "category", "title", "owner", "department", "cycle", "status", "source", "updated_at"]
    list_filter = ["pillar", "category", "status", "cycle", "source", "needs_match"]
    search_fields = ["title", "owner__full_name", "import_ref"]
    raw_id_fields = ["owner", "submitted_by", "lineage", "organization", "verified_by"]
    inlines = [ContributorInline]


admin.site.register(EvidenceFile, list_display=["id", "submission", "field", "original_name", "size"])
admin.site.register(ReviewEvent, list_display=["submission", "action", "actor", "created_at"])
admin.site.register(SavedView, list_display=["user", "name", "created_at"])
