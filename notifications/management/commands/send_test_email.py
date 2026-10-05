"""Send one test email through the configured backend (Mailpit locally).

    docker exec -it oric_local-backend-1 python manage.py send_test_email you@example.test
    → open http://localhost:8035
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send a test email via the configured SMTP server (Mailpit in local Docker)."

    def add_arguments(self, parser):
        parser.add_argument("to", nargs="?", default="test@oric.test")

    def handle(self, *args, **o):
        sent = send_mail(
            "[ORIC Data Portal] Test email",
            "If you can read this, outgoing email works.\n\n— ORIC, NED University",
            settings.DEFAULT_FROM_EMAIL,
            [o["to"]],
        )
        where = (
            "Open the Mailpit inbox at http://localhost:8035"
            if settings.EMAIL_HOST == "mailpit"
            else f"Sent via {settings.EMAIL_HOST}:{settings.EMAIL_PORT}"
        )
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} message to {o['to']}. {where}"))
