from django.contrib import admin

from .models import ContactMessage, Department, Faculty, Organization, ReportingCycle, TeamMember

admin.site.register(Faculty, list_display=["code", "name", "dean", "is_active"], raw_id_fields=["dean"])
admin.site.register(Department, search_fields=["name", "code"],
                    list_display=["name", "code", "faculty", "chair", "is_active"], raw_id_fields=["chair", "co_chairs"])
admin.site.register(Organization, search_fields=["name"], list_display=["name", "kind", "country"])
admin.site.register(ReportingCycle, list_display=["label", "year", "status", "submission_deadline"])
admin.site.register(TeamMember, list_display=["name", "title", "order", "is_active"])
admin.site.register(ContactMessage, list_display=["name", "email", "subject", "created_at", "handled"])
