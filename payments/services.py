# payments/services.py
"""
Business-level operations used by the payments views AND the M-Pesa callback.
Every entry point is idempotent.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from guestaccount.models import GuestBooking
from guestaccount.connectors import create_source_row
from notifications.services import on_payment_succeeded  # noqa — safe even if unused
from .models import PaymentAttempt, Receipt


# ---------------------------------------------------------------------------
# Policy helper
# ---------------------------------------------------------------------------
def _policy_of(booking):
    try:
        return booking.payment_policy or 'pay_now'
    except Exception:
        return 'pay_now'


def _deposit_percent_of(booking):
    try:
        listing = booking.listing
        return int(getattr(listing, 'deposit_percent', 0) or 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Create attempt
# ---------------------------------------------------------------------------
@transaction.atomic
def create_attempt(booking, method='mpesa', phone='', user=None,
                   override_amount=None):
    """
    Create a PaymentAttempt for the balance (or a deposit portion).
    Idempotent: returns an existing pending/processing attempt if one matches.
    """
    total = booking.total_amount or Decimal('0.00')
    paid = booking.amount_paid or Decimal('0.00')
    remaining = total - paid
    if remaining <= 0:
        raise ValueError('Nothing left to pay on this booking.')

    policy = _policy_of(booking)
    deposit_pct = _deposit_percent_of(booking)

    # Decide how much to charge now
    if override_amount is not None:
        amount = Decimal(str(override_amount))
        is_deposit = False
    elif policy == 'pay_deposit' and deposit_pct > 0 and paid == 0:
        amount = (total * Decimal(deposit_pct) / Decimal('100')).quantize(Decimal('0.01'))
        is_deposit = True
    else:
        amount = remaining
        is_deposit = False

    if amount <= 0:
        raise ValueError('Computed amount must be positive.')

    existing = PaymentAttempt.objects.filter(
        guest_booking=booking,
        method=method,
        status__in=['pending', 'processing'],
        amount=amount,
    ).first()
    if existing:
        return existing

    attempt = PaymentAttempt.objects.create(
        guest_booking=booking,
        user=user or booking.user,
        amount=amount,
        method=method,
        mpesa_phone=phone,
        currency='KES',
        status='pending',
        policy=policy,
        is_deposit=is_deposit,
        deposit_percent=deposit_pct,
    )
    return attempt


# ---------------------------------------------------------------------------
# Complete attempt
# ---------------------------------------------------------------------------
@transaction.atomic
def complete_attempt(attempt, provider_receipt='', extra=None):
    """
    Mark attempt succeeded, credit the booking, sync everything, issue a receipt,
    and notify the guest + org. Idempotent.
    """
    if attempt.status == 'succeeded':
        return attempt

    attempt.mark_succeeded(provider_receipt=provider_receipt, extra=extra)
    booking = attempt.guest_booking

    # Credit the booking
    booking.amount_paid = (booking.amount_paid or Decimal('0.00')) + attempt.amount

    # Create the source row (bnb.Booking etc.) if it doesn't exist yet
    if not booking.source_app:
        app, model, obj_id = create_source_row(booking)
        if app and model and obj_id:
            booking.source_app = app
            booking.source_model = model
            booking.source_id = obj_id

    # Decide final booking status
    is_paid_in_full = booking.amount_paid >= booking.total_amount and booking.total_amount > 0
    if is_paid_in_full:
        booking.status = 'confirmed'
        booking.paid_at = timezone.now()
        attempt.paid_in_full_at = timezone.now()
        attempt.save(update_fields=['paid_in_full_at'])

    booking.save()

    # Mirror the money into the underlying product row
    _sync_to_product(booking)

    # Lock the listing (date-range kinds only)
    if is_paid_in_full and booking.start_date and booking.end_date:
        try:
            booking.listing.availability_blocks.update_or_create(
                guest_booking=booking,
                defaults={
                    'listing': booking.listing,
                    'start_date': booking.start_date,
                    'end_date': booking.end_date,
                    'status': 'confirmed',
                },
            )
        except Exception:
            pass

    # Issue a receipt (only once per booking, and only when fully paid)
    receipt = Receipt.objects.filter(guest_booking=booking).first()
    if is_paid_in_full and not receipt:
        receipt = Receipt.objects.create(
            guest_booking=booking,
            payment_attempt=attempt,
            amount=booking.total_amount,
            currency='KES',
            notes=f'Payment received via {attempt.get_method_display()}',
        )

    # Notify guest + org
    try:
        on_payment_succeeded(booking, attempt, receipt=receipt)
    except Exception:
        pass

    return attempt


# ---------------------------------------------------------------------------
# Fail / refund
# ---------------------------------------------------------------------------
@transaction.atomic
def fail_attempt(attempt, reason='', extra=None):
    if attempt.status == 'failed':
        return attempt
    attempt.mark_failed(reason=reason, extra=extra)
    return attempt


@transaction.atomic
def refund_attempt(attempt, note=''):
    if attempt.status != 'succeeded':
        raise ValueError('Only a succeeded attempt can be refunded.')

    booking = attempt.guest_booking
    booking.amount_paid = max(
        Decimal('0.00'),
        (booking.amount_paid or Decimal('0.00')) - attempt.amount,
    )
    if booking.amount_paid < booking.total_amount:
        booking.status = 'pending'
        booking.paid_at = None
    booking.save()

    attempt.mark_refunded(note=note)

    # Release the listing
    try:
        booking.listing.availability_blocks.filter(
            guest_booking=booking,
        ).update(status='released')
    except Exception:
        pass

    return attempt


# ---------------------------------------------------------------------------
# Cash payment recorded by the org
# ---------------------------------------------------------------------------
@transaction.atomic
def record_cash_payment(booking, amount, recorded_by=None, note=''):
    """
    Used by org staff for pay-on-arrival / pay-on-delivery.
    Creates a `succeeded` PaymentAttempt(method='cash') and mirrors the amount.
    """
    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValueError('Amount must be positive.')

    attempt = PaymentAttempt.objects.create(
        guest_booking=booking,
        user=booking.user,
        recorded_by=recorded_by,
        amount=amount,
        method='cash',
        status='succeeded',
        currency='KES',
        policy=_policy_of(booking),
        provider_payload={'note': note, 'recorded_by': getattr(recorded_by, 'pk', None)},
        completed_at=timezone.now(),
    )
    return complete_attempt(attempt, provider_receipt='CASH-' + attempt.reference)


# ---------------------------------------------------------------------------
# Sync into the source product row
# ---------------------------------------------------------------------------
def _sync_to_product(booking):
    try:
        if booking.source_app == 'bnb' and booking.source_model == 'Booking':
            from bnb.models import Booking as BnbBooking
            row = BnbBooking.objects.get(pk=booking.source_id)
            row.amount_paid = booking.amount_paid
            row.total_amount = booking.total_amount
            row.status = 'confirmed' if booking.status == 'confirmed' else row.status
            row.save()
        elif booking.source_app == 'tours' and booking.source_model == 'TourBooking':
            from tours.models import TourBooking
            row = TourBooking.objects.get(pk=booking.source_id)
            row.amount_paid = booking.amount_paid
            row.total_amount = booking.total_amount
            row.status = 'confirmed'
            row.save()
        elif booking.source_app == 'restaurant' and booking.source_model == 'Order':
            from restaurant.models import Order
            row = Order.objects.get(pk=booking.source_id)
            row.total_amount = booking.total_amount
            row.amount_paid = booking.amount_paid
            if row.status == 'new':
                row.status = 'preparing'
            row.save()
        elif booking.source_app == 'laundry' and booking.source_model == 'LaundryOrder':
            from laundry.models import LaundryOrder
            row = LaundryOrder.objects.get(pk=booking.source_id)
            row.amount_paid = booking.amount_paid
            row.total_amount = booking.total_amount
            row.save()
    except Exception:
        pass