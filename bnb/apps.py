# bnb/apps.py
import os
import sys
import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class BnbConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bnb'

    def ready(self):
        # 1. Always register signals — this must happen in EVERY process
        #    (parent, child, gunicorn workers, celery workers, etc.)
        import bnb.signals  # noqa: F401 — register all receivers

        # 2. Decide whether this process should run the backfill.
        #
        #    Django's `runserver` spawns TWO processes:
        #      • parent  (the file watcher) — RUN_MAIN is NOT set
        #      • child   (the actual worker) — RUN_MAIN == 'true'
        #
        #    Only the child should touch the DB. If the parent queries
        #    the DB during ready(), Django's auto-reloader breaks and
        #    the server runs stale code until you Ctrl+C + restart.
        #
        #    In production (gunicorn / uwsgi / celery), there is no
        #    auto-reloader, so every worker should run the backfill once.
        argv = ' '.join(sys.argv).lower()

        is_runserver_child = (
            'runserver' in argv
            and os.environ.get('RUN_MAIN') == 'true'
        )
        is_production_worker = (
            'gunicorn' in argv
            or 'uwsgi' in argv
            or 'daphne' in argv
            or 'celery' in argv
        )

        if not (is_runserver_child or is_production_worker):
            # Parent watcher, migrate, makemigrations, collectstatic,
            # shell, test — all skip the backfill.
            return

        try:
            self._auto_backfill_ledger()
        except Exception:
            logger.exception('[bnb] Ledger auto-backfill failed on startup')

    def _auto_backfill_ledger(self):
        """
        Ensure every existing Booking / Expense / Revenue has its
        ledger mirror (LedgerEntry).

        Idempotent: re-running does nothing when the ledger is already
        consistent. Safe to call once per worker on startup.
        """
        # Double-guard: even if we somehow get here during a management
        # command that runs the full Django app (some tests do), skip.
        argv = ' '.join(sys.argv).lower()
        if any(
            cmd in argv
            for cmd in ('migrate', 'makemigrations', 'collectstatic', 'test')
        ):
            return

        from .models import Booking, Expense, Revenue
        from .signals import (
            reconcile_booking_ledger,
            expense_synced,
            extra_revenue_synced,
        )

        # Bookings → reconcile every one (idempotent; posts revenue
        # where status qualifies, posts reversal where cancelled, etc.)
        for booking in (
            Booking.objects
            .select_related('property__organization')
            .iterator(chunk_size=200)
        ):
            reconcile_booking_ledger(booking)

        # Expenses → upsert the ledger mirror (uses the FIXED
        # _combine_dt that respects Africa/Nairobi time).
        for expense in (
            Expense.objects
            .select_related('category', 'property')
            .iterator(chunk_size=200)
        ):
            expense_synced(
                sender=Expense, instance=expense, created=False,
            )

        # Extra revenues (minibar, late checkout, cleaning fee, …)
        for revenue in Revenue.objects.iterator(chunk_size=200):
            extra_revenue_synced(
                sender=Revenue, instance=revenue, created=False,
            )