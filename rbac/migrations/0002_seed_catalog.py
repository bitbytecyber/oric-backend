"""Seed the capability catalog + built-in roles.

Convention (from sis_backend): every change to rbac/capability_catalog.py ships
a data migration like this one — sync rows, then grant additively — otherwise a
new key has no DB row and silently never appears for anyone.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from rbac.services.seed import seed_roles, sync_capabilities

    Capability = apps.get_model("rbac", "Capability")
    AccessRole = apps.get_model("rbac", "AccessRole")
    RoleCapability = apps.get_model("rbac", "RoleCapability")
    sync_capabilities(Capability)
    seed_roles(reconcile=False, AccessRole=AccessRole, Capability=Capability, RoleCapability=RoleCapability)


class Migration(migrations.Migration):
    dependencies = [("rbac", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
