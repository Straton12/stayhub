# laundry/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LaundryService, LaundryOrder
from .views import _ensure_listing_for_service, _notify


@receiver(post_save, sender=LaundryService)
def _sync_service_listing(sender, instance, created, **kwargs):
    if created or instance.listing_id is None:
        try:
            _ensure_listing_for_service(instance)
        except Exception:
            pass


@receiver(post_save, sender=LaundryOrder)
def _sync_order_status(sender, instance, created, **kwargs):
    try:
        if created and instance.guest_booking_id:
            _notify(
                organization=instance.organization,
                event='laundry.order.created',
                subject=f"New laundry order {instance.reference}",
                body=f"{instance.customer_name}",
                guest_booking=instance.guest_booking,
                phone=instance.customer_phone,
            )
        elif not created:
            instance._sync_guest_booking()
    except Exception:
        pass