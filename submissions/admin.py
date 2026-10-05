from django.contrib import admin

from .models import EvidenceFile, ReviewEvent, SectionEntry, Submission


class EntryInline(admin.TabularInline):
    model = SectionEntry
    extra = 0
    fields = ["section", "data"]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["id", "pillar", "faculty_name", "department", "cycle", "status", "updated_at"]
    list_filter = ["pillar", "status", "cycle", "department"]
    search_fields = ["faculty_name", "faculty_email"]
    inlines = [EntryInline]


admin.site.register(SectionEntry, list_display=["id", "submission", "section", "updated_at"])
admin.site.register(EvidenceFile, list_display=["id", "entry", "field", "original_name", "size"])
admin.site.register(ReviewEvent, list_display=["submission", "action", "actor", "created_at"])
