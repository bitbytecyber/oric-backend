"""Make sure the funding-agency dropdown values (submissions.registry.FUNDING_AGENCIES) exist as organizations,
with the long spellings as aliases so free-text answers resolve to the same row."""
from django.db import migrations

AGENCIES = {
    "HEC": ["Higher Education Commission", "Higher Education Commission (HEC)", "HEC Pakistan", "H.E.C"],
    "MoST": ["Ministry of Science and Technology", "Ministry of Science & Technology", "MOST"],
    "NED": ["NED University", "NEDUET", "NED University of Engineering and Technology", "NED UET"],
    "NEDAASC": ["NED Alumni Association of Southern California", "NEDAASC USA",
                "NED Alumini Association Southern California (NEDAASC)"],
    "Sindh HEC": ["Sindh Higher Education Commission", "Sindh Higher Education Commission (SHEC)", "SHEC"],
    "UNESCO": ["United Nations Educational, Scientific and Cultural Organization"],
    "European Commission": ["EU", "European Union", "Erasmus+", "Erasmus + (Europe)"],
}


def seed(apps, schema_editor):
    Organization = apps.get_model("org", "Organization")
    for name, aliases in AGENCIES.items():
        spellings = {s.lower() for s in [name, *aliases]}
        org = Organization.objects.filter(name__iexact=name).first()
        if org is None:
            org = next((o for o in Organization.objects.exclude(aliases=[])
                        if spellings & {a.lower() for a in o.aliases}), None)
        if org is None:
            org = Organization.objects.create(name=name, kind="funder")
        known = {a.lower() for a in org.aliases}
        org.aliases = [*org.aliases, *(a for a in aliases if a.lower() not in known and a.lower() != org.name.lower())]
        org.save(update_fields=["aliases"])


class Migration(migrations.Migration):
    dependencies = [("org", "0003_reporting_cycle_framework")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
