import uuid

from django.db import migrations


def backfill(apps, schema_editor):
    InstitutionProfile = apps.get_model("scorecard", "InstitutionProfile")
    for p in InstitutionProfile.objects.all():
        staff = p.staff if isinstance(p.staff, list) else []
        changed = False
        for row in staff:
            if isinstance(row, dict) and not row.get("id"):
                row["id"] = uuid.uuid4().hex
                changed = True
        if changed:
            InstitutionProfile.objects.filter(pk=p.pk).update(staff=staff)


class Migration(migrations.Migration):
    dependencies = [("scorecard", "0002_institution_evidence")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
