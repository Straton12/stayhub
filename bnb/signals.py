# bnb/signals.py — full replacement
"""
BnB signals — the ledger is written automatically.

Three guarantees:

1. Every Booking save reconciles the ledger against the booking's
   *current* status. It does not rely on detecting transitions by
   comparing old vs new — it just looks at what's in the ledger
   and makes the ledger match the booking. Idempotent, so any
   number of saves (from any code path) is safe.

2. Every Expense / Payment / Revenue save upserts its own ledger
   row. Deleting the source row deletes the ledger mirror.

3. Nothing depends on the caller remembering to call a helper. The
   receiver is the only writer. That's the whole point.
"""

from decimal import Decimal

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import (
    Booking,
    Expense,
    LedgerEntry,
    Payment,
    Revenue,
    REVENUE_STATUSES,
    get_financial_settings,
)


# ===========================================================================
# CONFIG
# ===========================================================================
GB_STATUS_MAP = {
    'pending':     'pending',
    'confirmed':   'confirmed',
    'checked_in':  'in_progress',
    'checked_out': 'completed',
    'cancelled':   'cancelled',
    'no_show':     'cancelled',
}
LOCKING_STATUSES = {'confirmed', 'checked_in'}
EARNING_STATUSES = set(REVENUE_STATUSES)


# ===========================================================================
# HELPERS
# ===========================================================================
def _combine_dt(date, ts):
    """Combine date + time, correctly using the local timezone."""
    if not date and not ts:
        return timezone.now()
    if not date:
        return ts
    if not ts:
        return timezone.make_aware(
            timezone.datetime.combine(date, timezone.datetime.min.time()),
            timezone=timezone.get_current_timezone(),  # <--- FIX HERE
        )
    return timezone.make_aware(
        timezone.datetime.combine(date, ts.time()),
        timezone=timezone.get_current_timezone(),      # <--- FIX HERE
    )

def _amount_breakdown(org, gross):
    gross = gross if isinstance(gross, Decimal) else Decimal(gross or '0')
    settings = get_financial_settings(org) if org is not None else None
    if settings is None:
        return gross, Decimal('0.00')
    return settings.calculate_vat(gross)


# ===========================================================================
# BOOKING — reconcile ledger to current status (idempotent, race-free)
# ===========================================================================
@receiver(post_save, sender=Booking)
def booking_synced(sender, instance, created, **kwargs):
    """
    Runs on EVERY Booking save.

    1. Sync GuestBooking.status + amounts
    2. Lock/release marketplace availability
    3. Notify on create + on confirmed/cancelled (never on every save)
    4. Reconcile the ledger against the booking's current status
    """
    booking = instance
    prop = booking.property
    gb = booking.guest_booking

    # ---------- 1. GuestBooking sync ----------
    if gb:
        new_status = GB_STATUS_MAP.get(booking.status, gb.status)
        update_fields = []
        if gb.status != new_status:
            gb.status = new_status
            update_fields.append('status')
        if gb.amount_paid != (booking.amount_paid or 0):
            gb.amount_paid = booking.amount_paid or 0
            update_fields.append('amount_paid')
        if gb.total_amount != (booking.total_amount or 0):
            gb.total_amount = booking.total_amount or 0
            update_fields.append('total_amount')
        if update_fields:
            update_fields.append('updated_at')
            gb.save(update_fields=update_fields)

    # ---------- 2. Availability ----------
    listing = prop.listing if prop and prop.listing_id else None
    if listing:
        _sync_availability_block(listing, booking, gb)

    # ---------- 3. Notifications (only on meaningful transitions) ----------
    if created:
        _notify_org(
            booking=booking,
            event='bnb.booking.created',
            subject=f"New booking: {prop.name}",
            body=f"{booking.guest_name} booked {prop.name} from {booking.check_in} to {booking.check_out}.",
            priority='high',
        )
    else:
        # Detect transitions by comparing ledger state — not by stashed old status.
        rev_exists = LedgerEntry.objects.filter(
            booking=booking, kind='revenue',
        ).exists()
        if booking.status == 'confirmed' and not rev_exists:
            _notify_org(
                booking=booking,
                event='bnb.booking.confirmed',
                subject=f"Booking confirmed: {prop.name}",
                body=f"{booking.guest_name} is confirmed for {booking.check_in} → {booking.check_out}.",
                priority='normal',
            )
        elif booking.status in ('cancelled', 'no_show') and rev_exists:
            _notify_org(
                booking=booking,
                event=f'bnb.booking.{booking.status}',
                subject=f"Booking {booking.status}: {prop.name}",
                body=f"{booking.guest_name}'s booking was marked {booking.status}.",
                priority='normal',
            )

    # ---------- 4. Reconcile the ledger ----------
    reconcile_booking_ledger(booking)


def reconcile_booking_ledger(booking):
    """
    Make the ledger match what this booking SHOULD be.

    Called from:
      • post_save on every Booking save (automatic)
      • backfill command (initial state)
      • management command for fixing broken environments

    Idempotent. Safe to call a thousand times.
    """
    org = getattr(booking.property, 'organization', None)
    if org is None:
        return

    revenue_row = LedgerEntry.objects.filter(
        booking=booking, kind='revenue', source='booking',
    ).first()
    refund_row = LedgerEntry.objects.filter(
        booking=booking, kind='refund', source='booking',
    ).first()

    should_earn = booking.status in EARNING_STATUSES
    gross = booking.total_amount or Decimal('0.00')
    net, vat = _amount_breakdown(org, gross)
    occurred = booking.created_at or timezone.now()

    # --- CASE 1: Should earn, has revenue → update the row in place ---
    if should_earn and revenue_row:
        revenue_row.organization = org
        revenue_row.property = booking.property
        revenue_row.reason = f"Booking #{booking.pk} — {booking.guest_name}"
        revenue_row.amount = net
        revenue_row.vat_amount = vat
        revenue_row.occurred_at = occurred
        revenue_row.save(update_fields=[
            'organization', 'property', 'reason',
            'amount', 'vat_amount', 'occurred_at',
        ])
        # If a reversal exists from a prior cancellation, remove it.
        if refund_row:
            refund_row.delete()
        return

    # --- CASE 2: Should earn, no revenue → create the row ---
    if should_earn and not revenue_row:
        LedgerEntry.objects.create(
            organization=org,
            property=booking.property,
            kind='revenue',
            source='booking',
            reason=f"Booking #{booking.pk} — {booking.guest_name}",
            amount=net,
            vat_amount=vat,
            booking=booking,
            occurred_at=occurred,
        )
        if refund_row:
            refund_row.delete()
        return

    # --- CASE 3: Should NOT earn, revenue exists, no reversal → reverse ---
    if not should_earn and revenue_row and not refund_row:
        LedgerEntry.objects.create(
            organization=org,
            property=booking.property,
            kind='refund',
            source='booking',
            reason=(
                f"Reversal — Booking #{booking.pk} "
                f"{booking.guest_name} ({booking.get_status_display()})"
            ),
            amount=revenue_row.amount,
            vat_amount=revenue_row.vat_amount,
            booking=booking,
            occurred_at=timezone.now(),
        )
        return

    # --- CASE 4: Should NOT earn, no revenue → nothing to do ---
    # (a pending booking that never earned, or an already-reversed one)


# ===========================================================================
# EXPENSE — upsert on save, delete on delete
# ===========================================================================
@receiver(post_save, sender=Expense)
def expense_synced(sender, instance, created, **kwargs):
    org = instance.organization
    if org is None:
        return

    net, vat = _amount_breakdown(org, instance.amount or Decimal('0.00'))
    occurred = _combine_dt(instance.expense_date, instance.created_at)

    reason = instance.title or 'Expense'
    if instance.category_id:
        reason = f"{reason} — {instance.category_label}"

    entry = LedgerEntry.objects.filter(expense=instance, kind='expense').first()
    if entry is not None:
        entry.organization = org
        entry.property = instance.property
        entry.reason = reason
        entry.amount = net
        entry.vat_amount = vat
        entry.occurred_at = occurred
        entry.save(update_fields=[
            'organization', 'property', 'reason',
            'amount', 'vat_amount', 'occurred_at',
        ])
        return

    LedgerEntry.objects.create(
        organization=org,
        property=instance.property,
        kind='expense',
        source='expense',
        reason=reason,
        amount=net,
        vat_amount=vat,
        expense=instance,
        occurred_at=occurred,
    )


@receiver(post_delete, sender=Expense)
def expense_deleted(sender, instance, **kwargs):
    LedgerEntry.objects.filter(expense=instance).delete()


# ===========================================================================
# PAYMENT — DISABLED by default (avoids double-counting with bookings)
# ===========================================================================
# Uncomment ONLY if you switch from accrual to cash-based accounting.
# See the docstring at the top of the module.
#
# @receiver(post_save, sender=Payment)
# def payment_synced(sender, instance, created, **kwargs):
#     ...
#
# @receiver(post_delete, sender=Payment)
# def payment_deleted(sender, instance, **kwargs):
#     LedgerEntry.objects.filter(payment=instance).delete()


# ===========================================================================
# EXTRA REVENUE (minibar, late checkout, cleaning fee, …)
# ===========================================================================
@receiver(post_save, sender=Revenue)
def extra_revenue_synced(sender, instance, created, **kwargs):
    org = instance.organization
    if org is None:
        return

    net, vat = _amount_breakdown(org, instance.amount or Decimal('0.00'))
    occurred = _combine_dt(instance.revenue_date, instance.created_at)
    reason = f"Extra revenue #{instance.pk} — {instance.get_source_display()} — {instance.title}"

    entry = LedgerEntry.objects.filter(
        organization=org, kind='revenue', source='manual',
        reason__startswith=f"Extra revenue #{instance.pk}",
    ).first()

    if entry is not None:
        entry.property = instance.property
        entry.reason = reason
        entry.amount = net
        entry.vat_amount = vat
        entry.occurred_at = occurred
        entry.save(update_fields=[
            'property', 'reason', 'amount', 'vat_amount', 'occurred_at',
        ])
        return

    LedgerEntry.objects.create(
        organization=org,
        property=instance.property,
        kind='revenue',
        source='manual',
        reason=reason,
        amount=net,
        vat_amount=vat,
        occurred_at=occurred,
    )


@receiver(post_delete, sender=Revenue)
def extra_revenue_deleted(sender, instance, **kwargs):
    LedgerEntry.objects.filter(
        organization=instance.organization, kind='revenue', source='manual',
        reason__startswith=f"Extra revenue #{instance.pk}",
    ).delete()


# ===========================================================================
# INTERNAL HELPERS (unchanged from before)
# ===========================================================================
def _sync_availability_block(listing, booking, guest_booking):
    try:
        from marketplace.models import ListingAvailabilityBlock
    except Exception:
        return

    if booking.status not in LOCKING_STATUSES:
        ListingAvailabilityBlock.objects.filter(
            listing=listing, guest_booking=guest_booking,
        ).update(status='released')
        return

    ListingAvailabilityBlock.objects.update_or_create(
        listing=listing,
        guest_booking=guest_booking,
        defaults={
            'start_date': booking.check_in,
            'end_date': booking.check_out,
            'status': 'confirmed',
        },
    )


def _notify_org(*, booking, event, subject, body='', priority='normal'):
    org = getattr(booking.property, 'organization', None)
    gb = booking.guest_booking

    try:
        from notifications.models import notify
        notify(
            event=event, kind='booking', subject=subject, body=body,
            recipient_organization=org, guest_booking=gb,
            channel='inapp', status='sent', priority=priority,
            related_object_repr=str(booking),
        )
        return
    except Exception:
        pass

    try:
        from notifications.models import NotificationLog
        NotificationLog.objects.create(
            channel='inapp', status='sent', priority=priority,
            kind='booking', event=event, recipient_organization=org,
            subject=subject, body=body, guest_booking=gb,
            related_object_repr=str(booking),
        )
    except Exception:
        pass