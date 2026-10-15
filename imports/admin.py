from django.contrib import admin

from .models import ImportBatch, ImportRow

admin.site.register(ImportBatch, list_display=["id", "kind", "status", "original_name", "cycle", "created_at"])
admin.site.register(ImportRow, list_display=["id", "batch", "ref", "table", "status", "person_text"],
                    list_filter=["status", "table"])
