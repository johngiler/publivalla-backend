from django.core.management.base import BaseCommand

from apps.bidding.services.auction_services import close_expired_open_auctions


class Command(BaseCommand):
    help = "Cierra pujas abiertas cuya fecha de cierre ya pasó."

    def handle(self, *args, **options):
        n = close_expired_open_auctions()
        self.stdout.write(self.style.SUCCESS(f"Pujas cerradas automáticamente: {n}"))
