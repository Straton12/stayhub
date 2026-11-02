# bnb/management/commands/release_expired_blocks.py
"""
Sweep: mark any confirmed/pending ListingAvailabilityBlock whose end_date
has passed as 'released', so listings become bookable again.

The marketplace views already run this lazily on every public page load,
but this command lets you schedule a nightly cron job as a belt-and-braces
fallback for sites with low traffic.

Usage:
    python manage.py release_expired_blocks
    python manage.py release_expired_blocks --quiet
"""

from django.core.management.base import BaseCommand

from bnb.services import release_expired_blocks


class Command(BaseCommand):
    help = 'Release expired marketplace availability blocks.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet', action='store_true',
            help='Suppress the summary line.',
        )

    def handle(self, *args, **options):
        n = release_expired_blocks()
        if not options['quiet']:
            self.stdout.write(self.style.SUCCESS(
                f'Released {n} expired block(s).'
            ))