# tours/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import TourBooking, TourPackage
from .views import _ensure_listing_for_package, _notify


@receiver(post_save, sender=TourPackage)
def _sync_package_listing(sender, instance, created, **kwargs):
    if created or instance.listing_id is None:
        try:
            _ensure_listing_for_package(instance)
        except Exception:
            pass


@receiver(post_save, sender=TourBooking)
def _sync_booking_status(sender, instance, created, **kwargs):
    try:
        if created and instance.guest_booking_id:
            _notify(
                organization=instance.package.organization,
                event='tours.booking.created',
                subject=f"New tour booking {instance.reference}",
                body=f"{instance.customer_name} · {instance.package.name}",
                guest_booking=instance.guest_booking,
                email=instance.customer_email,
                phone=instance.customer_phone,
            )
        elif not created:
            instance._sync_guest_booking()
    except Exception:
        pass