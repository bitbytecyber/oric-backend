from django.core.management.base import BaseCommand

from rbac.services.seed import seed_roles, sync_capabilities


class Command(BaseCommand):
    help = "Sync the capability catalog and upsert built-in roles."

    def add_arguments(self, parser):
        parser.add_argument("--additive", action="store_true",
                            help="Only add missing grants; never remove grants from system roles.")

    def handle(self, *args, **opts):
        n = sync_capabilities()
        seed_roles(reconcile=not opts["additive"])
        self.stdout.write(self.style.SUCCESS(f"Synced {n} capabilities and seeded built-in roles."))
