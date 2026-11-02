# network/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from guestaccount.models import GuestBooking
from .models import NetworkProfile, Referral


@receiver(post_save, sender=GuestBooking)
def _maybe_auto_referral(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.source_app and instance.source_app != '':
        return
    try:
        source_org = getattr(instance.user, 'organization', None)
        if not source_org or source_org == instance.organization:
            return
        profile, _ = NetworkProfile.objects.get_or_create(organization=source_org)
        if not profile.offers_referrals:
            return
        Referral.objects.create(
            from_org=source_org,
            to_org=instance.organization,
            guest_booking=instance,
            guest_name=instance.customer_name,
            guest_phone=instance.customer_phone,
            guest_email=instance.customer_email,
            service_needed=instance.listing.title,
            notes='Auto-created from marketplace booking',
            source='marketplace',
            value=instance.total_amount,
            commission_rate=profile.commission_rate or 0,
            commission=(instance.total_amount or 0) * (profile.commission_rate or 0) / 100,
        )
    except Exception:
        pass