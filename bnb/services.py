# bnb/services.py
"""
Shared BnB service helpers.

These live here — NOT in views.py — so that signals.py can import them
without triggering a circular import (views imports models, signals
imports services, services imports models only).
"""

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .models import PricingRule


# ============================================================
#  Notifications
# ============================================================
def notify(organization, event, subject, body='', guest_booking=None,
           user=None, email='', phone=''):
    """Safe wrapper around notifications.NotificationLog."""
    try:
        from notifications.models import NotificationLog
        NotificationLog.objects.create(
            channel='inapp',
            status='sent',
            recipient_user=user,
            recipient_organization=organization,
            to_email=email,
            to_phone=phone,
            subject=subject,
            body=body,
            event=event,
            related_object_repr=subject,
            guest_booking=guest_booking,
        )
    except Exception:
        pass


# ============================================================
#  Marketplace listing publishing
# ============================================================
def publish_property(prop, *, auto_approve=False):
    """
    Push a Property into the marketplace Listing using the canonical
    publishing.publish() helper. Creates or updates the linked listing
    and refreshes the gallery images.
    """
    try:
        from marketplace.publishing import publish
    except Exception:
        return None

    listing = publish(
        prop,
        source_app='bnb',
        source_model='Property',
        category_slug=(prop.category.slug if prop.category_id else 'stays'),
        title=prop.name,
        short_description=prop.short_description or '',
        description=prop.description or '',
        location=prop.location_label or '',
        address=prop.address or '',
        latitude=prop.latitude,
        longitude=prop.longitude,
        price=prop.price,
        price_unit=prop.price_unit or 'per night',
        max_guests=prop.max_guests,
        bedrooms=prop.bedrooms,
        baths=prop.baths,
        contact_phone=prop.phone or '',
        contact_email=prop.email or '',
        whatsapp=prop.whatsapp or '',
        website=prop.website or '',
        facebook=prop.facebook or '',
        instagram=prop.instagram or '',
        twitter=prop.twitter or '',
        tiktok=prop.tiktok or '',
        youtube=prop.youtube or '',
        auto_approve=auto_approve,
    )

    if listing:
        # Sync the cover image file
        if prop.cover_image:
            listing.cover_image = prop.cover_image
            listing.save(update_fields=['cover_image'])

        # Sync the gallery
        try:
            from marketplace.models import ListingImage
            ListingImage.objects.filter(listing=listing).delete()
            for i, img in enumerate(prop.images):
                if img:
                    ListingImage.objects.create(
                        listing=listing, image=img, display_order=i + 1,
                    )
        except Exception:
            pass

        if prop.listing_id != listing.id:
            prop.listing = listing
            prop.save(update_fields=['listing'])

    return listing


# ============================================================
#  Booking ↔ GuestBooking sync
# ============================================================
def sync_guest_booking_from_booking(booking):
    """
    Ensure a guestaccount.GuestBooking exists for this bnb.Booking.
    Uses booking.property.listing as the marketplace listing.
    """
    try:
        from guestaccount.models import GuestBooking
    except Exception:
        return None

    listing = booking.property.listing if booking.property_id else None
    if not listing:
        return None

    gb, created = GuestBooking.objects.update_or_create(
        source_app='bnb', source_model='Booking', source_id=booking.id,
        defaults={
            'user': (booking.guest.user
                     if booking.guest and booking.guest.user_id else None),
            'listing': listing,
            'organization': booking.property.organization,
            'kind': 'stay',
            'customer_name': booking.guest_name,
            'customer_email': booking.guest_email,
            'customer_phone': booking.guest_phone,
            'start_date': booking.check_in,
            'end_date': booking.check_out,
            'unit_price': booking.total_amount or 0,
            'quantity': 1,
            'subtotal': booking.total_amount or 0,
            'total_amount': booking.total_amount or 0,
            'amount_paid': booking.amount_paid or 0,
            'payment_policy': 'pay_now',
            'status': (
                'confirmed' if booking.status in ('confirmed', 'checked_in', 'checked_out')
                else ('cancelled' if booking.status == 'cancelled' else 'pending')
            ),
        },
    )

    if created:
        notify(
            organization=booking.property.organization,
            event='bnb.booking.created',
            subject=f"New booking: {booking.property.name}",
            body=(f"{booking.guest_name} booked {booking.property.name} "
                  f"from {booking.check_in} to {booking.check_out}."),
            guest_booking=gb,
            email=booking.guest_email,
            phone=booking.guest_phone,
        )

    if booking.guest_booking_id != gb.id:
        booking.guest_booking = gb
        booking.save(update_fields=['guest_booking'])
    return gb


# ============================================================
#  Listing availability (block / release)
# ============================================================
def lock_listing_for_booking(booking):
    """Create or update a ListingAvailabilityBlock when a booking is confirmed."""
    try:
        from marketplace.models import ListingAvailabilityBlock
    except Exception:
        return
    listing = booking.property.listing if booking.property_id else None
    if not listing:
        return
    ListingAvailabilityBlock.objects.update_or_create(
        listing=listing, guest_booking=booking.guest_booking,
        defaults={
            'start_date': booking.check_in,
            'end_date': booking.check_out,
            'status': 'confirmed',
        },
    )


def release_listing_for_booking(booking):
    """Mark this booking's availability block as released."""
    if not booking.guest_booking_id:
        return
    try:
        from marketplace.models import ListingAvailabilityBlock
        ListingAvailabilityBlock.objects.filter(
            guest_booking=booking.guest_booking,
        ).update(status='released')
    except Exception:
        pass


def release_expired_blocks():
    """
    Sweep: mark any confirmed/pending listing-availability block whose
    end_date has already passed as 'released' so listings become
    bookable again.
    """
    try:
        from marketplace.models import ListingAvailabilityBlock
    except Exception:
        return 0
    today = timezone.now().date()
    return ListingAvailabilityBlock.objects.filter(
        status__in=['pending', 'confirmed'],
        end_date__lte=today,
    ).update(status='released')


# ============================================================
#  Pricing rules
# ============================================================
def apply_pricing_rules(base_price, property, nights=1, guests=1):
    """
    Compute the effective price for a stay, given the property's
    active pricing rules.

    Returns a dict with:
        {
            'base_price':   Decimal — nightly rate before discounts
            'nights':       int,
            'subtotal':     Decimal — base_price × nights
            'discount_pct': Decimal — total discount % from all rules
            'discount':     Decimal — money saved via discounts
            'fixed_fees':   Decimal — sum of all fixed amount fees
            'total':        Decimal — final amount after discount + fees
            'min_nights':   int     — minimum nights enforced by rules
            'notes':        list    — human-readable summary lines
        }

    Rules can be organisation-wide (property=None) or scoped to a
    specific property. Both apply.

    Safe to call with a property that has no rules — returns the
    untouched base price and empty adjustments.
    """
    base_price = Decimal(str(base_price or 0))
    nights = max(int(nights or 1), 1)
    subtotal = base_price * Decimal(nights)

    # ---- Load active rules that apply to this property ----
    rules = []
    try:
        rules = list(
            PricingRule.objects.filter(
                Q(applies_to_property=property) | Q(applies_to_property__isnull=True),
                organization=getattr(property, 'organization', None),
                is_active=True,
            )
        )
    except Exception:
        rules = []

    # ---- Defaults ----
    min_nights = 1
    discount_pct = Decimal('0')
    fixed_fees = Decimal('0')
    notes = []

    # ---- Apply each rule ----
    for r in rules:
        # Numeric value as Decimal
        try:
            val = Decimal(str(r.value or 0))
        except Exception:
            val = Decimal('0')

        if r.rule_type == 'min_nights' and r.value_type == 'number':
            try:
                wanted = int(val)
                if wanted > min_nights:
                    min_nights = wanted
                    notes.append(f"Minimum {wanted} nights")
            except Exception:
                pass

        elif r.rule_type in ('weekly', 'monthly', 'early_bird', 'last_minute') \
                and r.value_type == 'percent':
            discount_pct += val
            notes.append(f"{r.label}: -{val:g}%")

        elif r.value_type == 'amount':
            fixed_fees += val
            notes.append(f"{r.label}: +KES {val:,.0f}")

        elif r.rule_type == 'tax' and r.value_type == 'percent':
            discount_pct -= val   # tax subtracts from the effective total
            notes.append(f"{r.label}: {val:g}%")

    # ---- Math ----
    discount = (subtotal * discount_pct / Decimal('100')).quantize(Decimal('0.01'))
    total = (subtotal - discount + fixed_fees).quantize(Decimal('0.01'))

    return {
        'base_price':   base_price,
        'nights':       nights,
        'subtotal':     subtotal,
        'discount_pct': discount_pct,
        'discount':     discount,
        'fixed_fees':   fixed_fees,
        'total':        total,
        'min_nights':   min_nights,
        'notes':        notes,
    }