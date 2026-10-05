from django.contrib import admin

from .models import ContactMessage, Department, ReportingCycle, TeamMember

admin.site.register(Department, search_fields=["name", "code"], list_display=["name", "code", "is_active"])
admin.site.register(ReportingCycle, list_display=["label", "year", "status", "submission_deadline"])
admin.site.register(TeamMember, list_display=["name", "title", "order", "is_active"])
admin.site.register(ContactMessage, list_display=["name", "email", "subject", "created_at", "handled"])
