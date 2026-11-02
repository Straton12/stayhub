# marketplace/publishing.py
"""
Helpers to publish / unpublish / approve / reject a listing from any of
the product apps (bnb, tours, restaurant, laundry).

Every product app calls `publish()` (or the higher-level `sync_from_source()`)
whenever it wants its object to appear on the marketplace.
"""

from django.utils import timezone

from .models import Listing, ListingCategory


CATEGORY_FOR_APP = {
    'bnb':        'stays',
    'tours':      'tours',
    'restaurant': 'food',
    'laundry':    'laundry',
}

DEFAULT_PRICE_UNIT = {
    'stays':     'per night',
    'tours':     'per person',
    'food':      'per item',
    'laundry':   'per item',
    'transport': 'per trip',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_org(source_obj):
    org = getattr(source_obj, 'organization', None)
    if org:
        return org
    try:
        return source_obj.property.organization
    except Exception:
        return None


def _coerce_decimal(value):
    """Best-effort conversion to a Decimal-compatible string, or None."""
    if value in (None, ''):
        return None
    return value


def publish(
    source_obj,
    *,
    source_app,
    source_model,
    category_slug=None,
    title=None,
    short_description='',
    description='',
    # Location
    location='',
    address='',
    latitude=None,
    longitude=None,
    # Commercial
    price=None,
    price_unit=None,
    max_guests=None,
    bedrooms=None,
    baths=None,
    # Contact
    contact_phone='',
    contact_email='',
    whatsapp='',
    # Socials
    website='',
    facebook='',
    instagram='',
    twitter='',
    tiktok='',
    youtube='',
    # Media / policy
    cover_image_url='',
    payment_policy='pay_now',
    service_fee_percent=None,
    pay_first=True,
    auto_approve=False,
):
    """
    Create or update a Listing row for a given product object.

    Behaviour:
      - New listings default to 'pending' (moderation queue).
      - Existing listings keep their status unless `auto_approve=True`.
      - A previously unpublished listing is returned to 'pending' on re-save.
      - Blank string params do NOT overwrite existing values (opt-in updates).
    """
    category_slug = category_slug or CATEGORY_FOR_APP.get(source_app, 'stays')
    category = ListingCategory.objects.filter(slug=category_slug).first()
    if not category:
        return None

    org = _resolve_org(source_obj)
    if not org:
        return None

    listing = Listing.objects.filter(
        source_app=source_app,
        source_model=source_model,
        source_id=source_obj.pk,
    ).first()

    price_unit = price_unit or DEFAULT_PRICE_UNIT.get(category_slug, 'per item')

    if listing is None:
        listing = Listing.objects.create(
            organization=org,
            category=category,
            source_app=source_app,
            source_model=source_model,
            source_id=source_obj.pk,
            title=title or str(source_obj),
            short_description=short_description or '',
            description=description or '',
            location=location or getattr(org, 'location', '') or '',
            address=address or '',
            latitude=_coerce_decimal(latitude),
            longitude=_coerce_decimal(longitude),
            price=price or 0,
            price_unit=price_unit,
            max_guests=max_guests or 2,
            bedrooms=bedrooms or 1,
            baths=baths or 1,
            contact_phone=contact_phone or '',
            contact_email=contact_email or '',
            whatsapp=whatsapp or '',
            website=website or '',
            facebook=facebook or '',
            instagram=instagram or '',
            twitter=twitter or '',
            tiktok=tiktok or '',
            youtube=youtube or '',
            cover_image_url=cover_image_url or '',
            payment_policy=payment_policy,
            service_fee_percent=(
                service_fee_percent if service_fee_percent is not None else 5
            ),
            pay_first=pay_first,
            status='pending',
        )
        if auto_approve:
            approve(listing)
        return listing

    # --- Update path -------------------------------------------------------
    listing.organization = org
    listing.category = category

    if title:
        listing.title = title
    if short_description:
        listing.short_description = short_description
    if description:
        listing.description = description

    # Location (only overwrite when provided)
    if location:
        listing.location = location
    if address:
        listing.address = address
    if latitude is not None:
        listing.latitude = _coerce_decimal(latitude)
    if longitude is not None:
        listing.longitude = _coerce_decimal(longitude)

    # Commercial
    if price is not None:
        listing.price = price
    if price_unit:
        listing.price_unit = price_unit
    if max_guests is not None:
        listing.max_guests = max_guests
    if bedrooms is not None:
        listing.bedrooms = bedrooms
    if baths is not None:
        listing.baths = baths

    # Contact — overwrite only when provided
    if contact_phone:
        listing.contact_phone = contact_phone
    if contact_email:
        listing.contact_email = contact_email
    if whatsapp:
        listing.whatsapp = whatsapp

    # Socials — overwrite only when provided
    if website:
        listing.website = website
    if facebook:
        listing.facebook = facebook
    if instagram:
        listing.instagram = instagram
    if twitter:
        listing.twitter = twitter
    if tiktok:
        listing.tiktok = tiktok
    if youtube:
        listing.youtube = youtube

    if cover_image_url:
        listing.cover_image_url = cover_image_url
    if service_fee_percent is not None:
        listing.service_fee_percent = service_fee_percent

    listing.payment_policy = payment_policy
    listing.pay_first = pay_first

    if listing.status == 'unpublished':
        listing.status = 'pending'
        listing.approved_at = None
        listing.approved_by = None

    listing.save()

    # Auto-approve on the update path too
    if auto_approve and listing.status != 'approved':
        approve(listing)

    return listing


def unpublish(source_obj, *, source_app, source_model):
    listing = Listing.objects.filter(
        source_app=source_app,
        source_model=source_model,
        source_id=source_obj.pk,
    ).first()
    if not listing:
        return None
    listing.status = 'unpublished'
    listing.is_active = False
    listing.save(update_fields=['status', 'is_active', 'updated_at'])
    return listing


def approve(listing, by_user=None):
    listing.status = 'approved'
    listing.is_active = True
    listing.approved_at = timezone.now()
    if by_user is not None:
        listing.approved_by = by_user
    listing.rejection_note = ''
    listing.save(update_fields=[
        'status', 'is_active', 'approved_at',
        'approved_by', 'rejection_note', 'updated_at',
    ])
    _notify(
        listing.organization,
        event='marketplace.listing.approved',
        subject=f'Listing approved: {listing.title}',
        body='Your listing is now live on the marketplace.',
    )
    return listing


def reject(listing, note='', by_user=None):
    listing.status = 'rejected'
    listing.is_active = False
    listing.rejection_note = note or ''
    if by_user is not None:
        listing.approved_by = by_user
    listing.save(update_fields=[
        'status', 'is_active', 'rejection_note',
        'approved_by', 'updated_at',
    ])
    _notify(
        listing.organization,
        event='marketplace.listing.rejected',
        subject=f'Listing rejected: {listing.title}',
        body=note or 'Your listing was rejected.',
    )
    return listing


def get_listing_for(source_obj, *, source_app, source_model):
    return Listing.objects.filter(
        source_app=source_app,
        source_model=source_model,
        source_id=source_obj.pk,
    ).first()


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------
def _notify(organization, *, event, subject, body=''):
    try:
        from notifications.models import NotificationLog
        NotificationLog.objects.create(
            channel='inapp',
            status='sent',
            recipient_organization=organization,
            event=event,
            subject=subject,
            body=body,
        )
    except Exception:
        pass