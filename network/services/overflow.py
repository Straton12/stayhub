# network/services/overflow.py

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from marketplace.models import Listing, ListingAvailabilityBlock
from network.models import NetworkFavorite, NetworkProfile, Referral


PRICE_TOLERANCE = 0.10  # ±10% — "same pricing" band


def find_overflow_match(referrer_org, start_date, end_date, base_listing):
    """
    Find a partner property that is available for [start_date, end_date]
    and priced within ±10% of base_listing.price.

    Search order:
      1. The referrer's favorites
      2. The wider network (orgs that have accepts_referrals=True)

    Returns (listing_or_None, match_reason_str).
    """
    if not (start_date and end_date and base_listing.price):
        return None, 'none'

    price = float(base_listing.price)
    low = price * (1 - PRICE_TOLERANCE)
    high = price * (1 + PRICE_TOLERANCE)

    def _available_qs():
        """Base queryset: approved, active, priced, same category,
        not the base listing itself, not the referrer's own."""
        return (
            Listing.objects
            .filter(
                status='approved',
                is_active=True,
                accepts_bookings=True,
                category=base_listing.category,
                price__gte=low,
                price__lte=high,
            )
            .exclude(pk=base_listing.pk)
            .exclude(organization=referrer_org)
            .select_related('organization', 'category')
        )

    def _is_free_on_dates(listing):
        """True if no confirmed/pending block overlaps the window."""
        return not ListingAvailabilityBlock.objects.filter(
            listing=listing,
            status__in=['pending', 'confirmed'],
            start_date__lt=end_date,
            end_date__gt=start_date,
        ).exists()

    # ---- 1. Favorites first ----
    favorite_ids = (
        NetworkFavorite.objects
        .filter(organization=referrer_org)
        .order_by('priority', '-created_at')
        .values_list('listing_id', flat=True)
    )
    if favorite_ids:
        fav_qs = _available_qs().filter(pk__in=favorite_ids)
        for listing in fav_qs:
            if _is_free_on_dates(listing):
                return listing, 'favorite'

    # ---- 2. Wider network ----
    accepting_org_ids = (
        NetworkProfile.objects
        .filter(accepts_referrals=True)
        .exclude(organization=referrer_org)
        .values_list('organization_id', flat=True)
    )
    network_qs = _available_qs().filter(organization_id__in=accepting_org_ids)
    for listing in network_qs.order_by('-average_rating', '-booking_count'):
        if _is_free_on_dates(listing):
            return listing, 'network'

    return None, 'none'


@transaction.atomic
def create_overflow_referral(referrer_org, guest_booking, base_listing):
    """
    Called when a guest booked ``base_listing`` but the referrer is
    overbooked for that date window.

    Creates a Referral row. If a match is found, marks it ``accepted``
    (auto) and returns the matched listing so the caller can:

      • swap ``guest_booking.listing`` to the matched listing
      • create the ListingAvailabilityBlock on the matched listing
      • notify the guest with the matched property's details

    If no match is found, the referral is marked ``no_match`` and the
    caller should notify the owner so they can resolve manually.

    Returns (referral, matched_listing_or_None).
    """
    # --------------------------------------------------------------
    # GuestBooking uses start_date / end_date, not check_in / check_out
    # --------------------------------------------------------------
    start = getattr(guest_booking, 'start_date', None)
    end = getattr(guest_booking, 'end_date', None)

    # GuestBooking stores customer_*, not guest_*
    guest_name = getattr(guest_booking, 'customer_name', '') or ''
    guest_phone = getattr(guest_booking, 'customer_phone', '') or ''
    guest_email = getattr(guest_booking, 'customer_email', '') or ''

    matched, reason = find_overflow_match(
        referrer_org, start, end, base_listing,
    )

    profile = getattr(referrer_org, 'network_profile', None)
    commission_rate = profile.commission_rate if profile else Decimal('0')

    # --------------------------------------------------------------
    # No match — record for visibility; caller will notify owner.
    # --------------------------------------------------------------
    if matched is None:
        referral = Referral.objects.create(
            from_org=referrer_org,
            to_org=referrer_org,           # self-reference; not a real transfer
            guest_booking=guest_booking,
            guest_name=guest_name,
            guest_phone=guest_phone,
            guest_email=guest_email,
            service_needed=f'{base_listing.title} ({start} → {end})',
            source='auto_overflow',
            status='no_match',
            is_auto=True,
            match_reason='none',
            commission_rate=commission_rate,
        )
        referral._notify(
            referrer_org,
            'network.overflow.no_match',
            f'Overflow booking — no partner available for {guest_name}',
            (
                f'Guest booked {base_listing.title} for '
                f'{start} → {end}. '
                f'No available partner found at matching price. '
                f'Please contact the guest directly.'
            ),
        )
        return referral, None

    # --------------------------------------------------------------
    # Match found — compute commission and create the referral.
    # --------------------------------------------------------------
    price = Decimal(str(matched.price))
    commission = (price * commission_rate / Decimal('100')).quantize(Decimal('0.01'))
    payout_kept = (price - commission).quantize(Decimal('0.01'))

    referral = Referral.objects.create(
        from_org=referrer_org,
        to_org=matched.organization,
        guest_booking=guest_booking,
        guest_name=guest_name,
        guest_phone=guest_phone,
        guest_email=guest_email,
        service_needed=(
            f'Overflow from {base_listing.title} ({start} → {end})'
        ),
        source='auto_overflow',
        status='accepted',              # accepted silently — guest already booked
        is_auto=True,
        match_reason=reason,
        commission_rate=commission_rate,
        value=price,
        commission=commission,
        referrer_payout=payout_kept,
        accepted_at=timezone.now(),
    )

    # ---- Notify referrer (A) — the reallocation notice + fee due ----
    referral._notify(
        referrer_org,
        'network.overflow.referred',
        f'Guest {guest_name} reallocated to {matched.organization.name}',
        (
            f'Booking for {base_listing.title} ({start} → {end}). '
            f'Referred to {matched.organization.name} — {matched.title}. '
            f'Referral fee due: KES {commission}.'
        ),
    )

    # ---- Notify receiver (X) — new guest + commission pending ----
    referral._notify(
        matched.organization,
        'network.overflow.received',
        f'New referral from {referrer_org.name} — {guest_name}',
        (
            f'{guest_name} ({start} → {end}) is arriving at '
            f'{matched.title}. '
            f'Commission to be paid to {referrer_org.name}: '
            f'KES {commission}.'
        ),
    )

    return referral, matched