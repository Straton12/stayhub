# notifications/signals.py
"""
Signals that trigger notifications.

Wired here:
  - GuestBooking created           → booking-created emails/SMS + org in-app
  - GuestBooking cancelled         → cancellation email
  - marketplace.Listing approved   → org notification
  - marketplace.Listing rejected   → org notification
  - marketplace.Review created     → org notification
  - network.Referral created       → receiver notification

Payment success is triggered explicitly from payments.services.complete_attempt()
because it needs access to the attempt and receipt.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from guestaccount.models import GuestBooking


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------
@receiver(post_save, sender=GuestBooking)
def _guest_booking_created(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.status != 'pending':
        return
    try:
        from .services import on_booking_created
        on_booking_created(instance)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------
@receiver(post_save, sender='marketplace.Listing')
def _listing_saved(sender, instance, created, **kwargs):
    """Fire only on transitions to approved / rejected."""
    try:
        if instance.status == 'approved' and not getattr(instance, '_notified_approved', False):
            # Only fire if we've never notified before
            from .services import on_listing_approved
            on_listing_approved(instance)
            instance._notified_approved = True
        elif instance.status == 'rejected':
            from .services import on_listing_rejected
            on_listing_rejected(instance)
    except Exception:
        pass


@receiver(post_save, sender='marketplace.Review')
def _review_created(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from .services import on_review_created
        on_review_created(instance)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
@receiver(post_save, sender='network.Referral')
def _referral_saved(sender, instance, created, **kwargs):
    if created:
        try:
            from .services import on_referral_created
            on_referral_created(instance)
        except Exception:
            pass