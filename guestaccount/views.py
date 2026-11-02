# guestaccount/views.py

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from marketplace.models import Listing, ListingAvailabilityBlock
from payments.models import PaymentAttempt, Receipt

from .connectors import create_source_row
from .models import GuestBooking, GuestProfile


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_guest(request):
    return request.user.is_authenticated and getattr(request.user, 'is_guest', False)


def _parse_date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def _resolve_billing_unit(listing):
    slug = (listing.category.slug or '').lower()
    if slug in ('stays', 'tours', 'laundry'):
        return 'per_night'
    return 'per_item'


def _collect_details(request, listing):
    """Gather per-category extra fields from POST into a JSON-friendly dict."""
    slug = listing.category.slug
    d = {}
    if slug == 'stays':
        d['guests'] = request.POST.get('guests', '1')
        d['special_requests'] = request.POST.get('special_requests', '')
    elif slug == 'tours':
        d['pickup'] = request.POST.get('pickup', '')
        d['guide_language'] = request.POST.get('guide_language', '')
    elif slug == 'food':
        d['delivery_address'] = request.POST.get('delivery_address', '')
        d['order_notes'] = request.POST.get('order_notes', '')
        d['order_type'] = request.POST.get('order_type', 'delivery')
    elif slug == 'laundry':
        d['pickup_address'] = request.POST.get('pickup_address', '')
        d['delivery_address'] = request.POST.get('delivery_address', '')
        d['items_description'] = request.POST.get('items_description', '')
    elif slug == 'transport':
        d['pickup'] = request.POST.get('pickup', '')
        d['dropoff'] = request.POST.get('dropoff', '')
        d['pickup_time'] = request.POST.get('pickup_time', '')
    return d


def _allowed_payment_policies(listing):
    slug = (listing.category.slug or '').lower()
    allowed = {'pay_now'}
    if slug in ('stays', 'tours'):
        allowed.add('pay_on_arrival')
    elif slug in ('food', 'laundry'):
        allowed.update({'pay_on_delivery', 'pay_on_arrival'})
    elif slug == 'transport':
        allowed.update({'pay_on_arrival', 'pay_on_completion'})
    else:
        allowed.update({'pay_on_arrival', 'pay_on_delivery', 'pay_on_completion'})
    try:
        if (listing.deposit_percent or 0) > 0:
            allowed.add('pay_deposit')
    except Exception:
        pass
    try:
        if listing.payment_policy:
            allowed.add(listing.payment_policy)
    except Exception:
        pass
    return allowed


def _resolve_payment_policy(listing):
    try:
        return listing.payment_policy or 'pay_now'
    except Exception:
        return 'pay_now'


def _notify(organization, event, subject, body='', guest_booking=None,
            user=None, email='', phone=''):
    """
    Org-facing in-app notification. Logs failures instead of swallowing
    them silently so issues surface in dev / Sentry.
    """
    try:
        from notifications.models import NotificationLog
        NotificationLog.objects.create(
            channel='inapp',
            status='sent',
            priority='high' if 'created' in event else 'normal',
            kind='booking',
            recipient_organization=organization,
            recipient_user=user,
            event=event,
            subject=subject,
            body=body or subject,
            related_object_repr=subject,
            guest_booking=guest_booking,
            to_email=email,
            to_phone=phone,
        )
    except Exception:
        logger.exception('Failed to create NotificationLog: %s', subject)


def _notify_guest(guest_booking, listing, subject, body,
                  event='guestaccount.booking.confirmed'):
    """
    Guest-facing notification. Uses the *matched* listing (which may
    differ from what the guest originally clicked) so the guest only
    ever sees one coherent property.
    """
    reference = ''
    try:
        reference = guest_booking.reference
    except Exception:
        reference = f'#{guest_booking.pk}'

    try:
        from notifications.models import NotificationLog
        NotificationLog.objects.create(
            channel='inapp',
            status='sent',
            priority='high',
            kind='booking',
            recipient_user=guest_booking.user,
            event=event,
            subject=subject,
            body=body,
            related_object_repr=reference,
            guest_booking=guest_booking,
            to_email=guest_booking.customer_email,
            to_phone=guest_booking.customer_phone,
        )
    except Exception:
        logger.exception('Failed to create guest NotificationLog: %s', subject)


def _run_overflow_matcher(booking, base_listing):
    """
    Try to reallocate an overbooked guest to a partner property.

    Returns (matched_listing_or_None, referral_or_None).

    Called from booking_new *after* the GuestBooking is saved. If a match
    is found, ``booking.listing`` is swapped to the matched listing and an
    availability block is created against the matched listing.
    """
    try:
        from network.services.overflow import create_overflow_referral
    except Exception:
        logger.exception('Could not import create_overflow_referral')
        return None, None

    try:
        referral, matched_listing = create_overflow_referral(
            referrer_org=booking.organization,
            guest_booking=booking,
            base_listing=base_listing,
        )
    except Exception:
        logger.exception('Overflow matcher failed')
        return None, None

    if matched_listing is None:
        return None, referral

    # Swap booking → matched listing, and create the availability block.
    # If the swap succeeds but the block fails, we keep the swap (the
    # referral already reflects the accepted transfer).
    try:
        with transaction.atomic():
            booking.listing = matched_listing
            booking.organization = matched_listing.organization
            booking.save(update_fields=['listing', 'organization', 'updated_at'])
    except Exception:
        logger.exception('Booking swap to matched listing failed')
        return None, referral

    try:
        ListingAvailabilityBlock.objects.create(
            listing=matched_listing,
            guest_booking=booking,
            start_date=booking.start_date,
            end_date=booking.end_date,
            status='confirmed',
        )
    except Exception:
        # Doesn't kill the referral — just log so you can investigate.
        logger.exception('Availability block creation failed for matched listing')

    return matched_listing, referral


# ---------------------------------------------------------------------------
# Guest home
# ---------------------------------------------------------------------------
@login_required
def home(request):
    if not _require_guest(request):
        return redirect('dashboard')

    bookings = (
        GuestBooking.objects
        .filter(user=request.user)
        .select_related('listing', 'listing__category', 'organization')
    )
    today = date.today()
    upcoming = bookings.filter(
        status__in=['confirmed', 'in_progress'],
        start_date__gte=today,
    ).order_by('start_date')
    pending = bookings.filter(status='pending').order_by('-created_at')
    past = bookings.filter(
        Q(status='completed') | Q(status='cancelled') | Q(status='refunded')
    ).order_by('-created_at')
    total_paid = bookings.filter(
        status__in=['confirmed', 'in_progress', 'completed']
    ).aggregate(s=Sum('amount_paid'))['s'] or Decimal('0.00')

    return render(request, 'guestaccount/home.html', {
        'bookings': bookings,
        'upcoming': upcoming,
        'pending': pending,
        'past': past,
        'total_paid': total_paid,
        'count_total': bookings.count(),
    })


# ---------------------------------------------------------------------------
# NEW BOOKING
# ---------------------------------------------------------------------------
@login_required
def booking_new(request, listing_slug):
    if not _require_guest(request):
        messages.info(request, 'Only guest accounts can book from the marketplace.')
        return redirect('dashboard')

    listing = get_object_or_404(
        Listing, slug=listing_slug, status='approved', is_active=True,
    )

    if not listing.accepts_bookings:
        messages.error(request, 'This listing is not accepting bookings right now.')
        return redirect('marketplace:listing_detail', slug=listing.slug)

    billing_unit = _resolve_billing_unit(listing)

    # Payment policy (from POST or fallback)
    allowed_policies = _allowed_payment_policies(listing)
    posted_policy = (request.POST.get('payment_policy') or '').strip()
    payment_policy = (
        posted_policy if posted_policy in allowed_policies
        else _resolve_payment_policy(listing)
    )

    if request.method == 'POST':
        name = (
            request.POST.get('customer_name', '').strip()
            or request.user.display_name
        )
        email = (
            request.POST.get('customer_email', '').strip()
            or request.user.email
        )
        phone = (
            request.POST.get('customer_phone', '').strip()
            or getattr(request.user, 'phone', '')
        )

        start_date = _parse_date(request.POST.get('start_date', '').strip())
        end_date = _parse_date(request.POST.get('end_date', '').strip())

        # Date validation
        if billing_unit == 'per_night':
            if not start_date or not end_date:
                messages.error(request, 'Please choose both a check-in and a check-out date.')
                return redirect('marketplace:listing_detail', slug=listing.slug)
            if end_date <= start_date:
                messages.error(request, 'Check-out must be after check-in.')
                return redirect('marketplace:listing_detail', slug=listing.slug)
            if start_date < date.today():
                messages.error(request, 'Check-in cannot be in the past.')
                return redirect('marketplace:listing_detail', slug=listing.slug)
            nights = max((end_date - start_date).days, 1)
        else:
            nights = 1
            start_date = start_date or date.today()
            end_date = end_date or start_date

        # Quantity
        try:
            quantity = int(request.POST.get('quantity') or 1)
        except (TypeError, ValueError):
            quantity = 1
        if quantity < 1:
            quantity = 1

        details = _collect_details(request, listing)
        unit_price = listing.price or Decimal('0.00')

        booking = GuestBooking(
            user=request.user,
            listing=listing,
            organization=listing.organization,
            kind={
                'stays':     'stay',
                'tours':     'tour',
                'food':      'food',
                'laundry':   'laundry',
                'transport': 'transport',
            }.get(listing.category.slug, 'other'),
            customer_name=name,
            customer_email=email,
            customer_phone=phone,
            start_date=start_date,
            end_date=end_date,
            details=details,
            unit_price=unit_price,
            quantity=quantity,
            nights=nights,
            billing_unit=billing_unit,
            amount_paid=Decimal('0.00'),
            payment_policy=payment_policy,
            guest_note=request.POST.get('guest_note', '').strip(),
        )
        booking.recalc_totals(save=False)
        booking.save()

        # ---------- Availability check + overflow reallocation ----------
        try:
            is_available = listing.is_available(start_date, end_date)
        except Exception:
            is_available = True

        overflow_used = False

        if not is_available:
            matched, referral = _run_overflow_matcher(booking, listing)
            if matched is not None:
                # booking.listing now points at the matched listing.
                listing = matched
                overflow_used = True
                messages.info(
                    request,
                    'Your booking is confirmed with our partner — '
                    'details have been sent to you.',
                )
            else:
                # No partner — owner will handle manually, guest warned.
                _notify(
                    organization=booking.organization,
                    event='guestaccount.booking.overbooked_no_match',
                    subject=f'⚠️ Overbooked booking — {booking.reference}',
                    body=(
                        f'{booking.customer_name} booked {listing.title} for '
                        f'{start_date} → {end_date}, but the property is '
                        f'already occupied for those dates and no partner '
                        f'was found. Please contact the guest to arrange '
                        f'alternate dates or refund.'
                    ),
                    guest_booking=booking,
                    user=request.user,
                    email=email, phone=phone,
                )
                messages.warning(
                    request,
                    'Your booking is pending — the host will contact you '
                    'shortly to confirm availability.',
                )
        else:
            # Normal path — create the availability block on the
            # originally requested listing.
            try:
                ListingAvailabilityBlock.objects.create(
                    listing=listing,
                    guest_booking=booking,
                    start_date=start_date,
                    end_date=end_date,
                    status='confirmed',
                )
            except Exception:
                logger.exception('Availability block creation failed')

        # ---------- Create underlying source row ----------
        app, model, pk = create_source_row(booking)
        if app and model and pk:
            booking.source_app = app
            booking.source_model = model
            booking.source_id = pk
            booking.save(update_fields=['source_app', 'source_model', 'source_id'])

        # ---------- Notify the owning org (may be the matched org) ----------
        nights_txt = (
            f' × {booking.nights} night{"s" if booking.nights != 1 else ""}'
            if booking.billing_unit == 'per_night' else ''
        )
        _notify(
            organization=booking.organization,
            event='guestaccount.booking.created',
            subject=f'New {booking.get_kind_display()}: {booking.reference}',
            body=(
                f'{name} · {booking.listing.title}{nights_txt} · '
                f'Total {booking.total_amount} {booking.currency} · '
                f'Payment: {booking.get_payment_policy_display()}'
            ),
            guest_booking=booking,
            user=request.user,
            email=email, phone=phone,
        )

        # ---------- Guest notification (single canonical point) ----------
        try:
            ref = booking.reference
        except Exception:
            ref = f'#{booking.pk}'
        _notify_guest(
            booking,
            listing,
            subject='Your booking has been received',
            body=(
                f'Hi {booking.customer_name}, we\'ve received your booking '
                f'for {listing.title} ({start_date} → {end_date}). '
                f'Reference: {ref}. '
                + (
                    'Payment will be collected on arrival.'
                    if booking.is_pay_later
                    else 'Please complete payment to confirm.'
                )
            ),
            event='guestaccount.booking.received',
        )

        # ---------- Pay-on-arrival: confirm directly ----------
        if booking.is_pay_later:
            booking.mark_confirmed(by_user=None)
            _notify_guest(
                booking,
                listing,
                subject='Your booking is confirmed',
                body=(
                    f'Hi {booking.customer_name}, your booking at '
                    f'{listing.title} is confirmed for '
                    f'{start_date} → {end_date}. '
                    f'Address: {listing.address or listing.location or "shared on arrival"}. '
                    f'Ref: {ref}'
                ),
            )
            messages.success(
                request,
                f'Booking created. Payment will be collected on '
                f'{payment_policy.replace("pay_on_", "").replace("_", " ")}. '
                f'We have sent the details to the host.',
            )
            return redirect('guestaccount:booking_detail', pk=booking.pk)

        # ---------- Pay-now / deposit: send to payment gateway ----------
        return redirect('guestaccount:booking_confirm', pk=booking.pk)

    # GET — render form
    return render(request, 'guestaccount/booking_new.html', {
        'listing': listing,
        'billing_unit': billing_unit,
        'today': date.today().isoformat(),
        'tomorrow': (date.today() + timedelta(days=1)).isoformat(),
        'service_fee_pct': listing.service_fee_percent or 0,
        'payment_policy': payment_policy,
        'allowed_payment_policies': _allowed_payment_policies(listing),
        'unit_price': listing.price or 0,
    })


# ---------------------------------------------------------------------------
# CONFIRM & PAY (unchanged)
# ---------------------------------------------------------------------------
@login_required
def booking_confirm(request, pk):
    if not _require_guest(request):
        return redirect('dashboard')

    booking = get_object_or_404(GuestBooking, pk=pk, user=request.user)
    if booking.status not in ('pending',):
        return redirect('guestaccount:booking_detail', pk=booking.pk)

    if request.method == 'POST':
        posted_policy = (request.POST.get('payment_policy') or '').strip()
        allowed = _allowed_payment_policies(booking.listing)
        if posted_policy and posted_policy in allowed and posted_policy != booking.payment_policy:
            booking.payment_policy = posted_policy
            booking.save(update_fields=['payment_policy', 'updated_at'])

        if booking.is_pay_later:
            booking.mark_confirmed()
            _notify_guest(
                booking,
                booking.listing,
                subject='Your booking is confirmed',
                body=(
                    f'Hi {booking.customer_name}, your booking at '
                    f'{booking.listing.title} is confirmed. '
                    f'Payment will be collected {booking.get_payment_policy_display().lower()}.'
                ),
            )
            messages.success(
                request,
                f'Booking confirmed. Payment will be collected '
                f'{booking.get_payment_policy_display().lower()}.',
            )
            return redirect('guestaccount:booking_detail', pk=booking.pk)

        return redirect('payments:initiate', booking_pk=booking.pk)

    return render(request, 'guestaccount/booking_confirm.html', {
        'booking': booking,
        'listing': booking.listing,
        'allowed_payment_policies': _allowed_payment_policies(booking.listing),
    })


# ---------------------------------------------------------------------------
# BOOKING DETAIL (unchanged)
# ---------------------------------------------------------------------------
@login_required
def booking_detail(request, pk):
    if not _require_guest(request):
        return redirect('dashboard')

    booking = get_object_or_404(
        GuestBooking.objects.select_related(
            'listing', 'listing__category', 'organization',
        ),
        pk=pk, user=request.user,
    )
    receipt = Receipt.objects.filter(guest_booking=booking).first()
    attempts = PaymentAttempt.objects.filter(guest_booking=booking).order_by('-created_at')

    return render(request, 'guestaccount/booking_detail.html', {
        'booking': booking,
        'receipt': receipt,
        'attempts': attempts,
        'source_row': booking.source_row,
        'can_review': booking.can_be_reviewed,
    })


# ---------------------------------------------------------------------------
# BOOKING CANCEL (unchanged)
# ---------------------------------------------------------------------------
@login_required
def booking_cancel(request, pk):
    if not _require_guest(request):
        return redirect('dashboard')

    booking = get_object_or_404(GuestBooking, pk=pk, user=request.user)

    if booking.status == 'confirmed' and booking.amount_paid > 0:
        messages.warning(
            request,
            'This booking is already paid. Contact the business to cancel and request a refund.',
        )
        return redirect('guestaccount:booking_detail', pk=booking.pk)

    if request.method == 'POST':
        booking.mark_cancelled()
        messages.success(request, 'Booking cancelled.')
        return redirect('guestaccount:home')

    return render(request, 'guestaccount/booking_cancel.html', {'booking': booking})


# ---------------------------------------------------------------------------
# REVIEWS (unchanged)
# ---------------------------------------------------------------------------
@login_required
def booking_review(request, pk):
    if not _require_guest(request):
        return redirect('dashboard')

    booking = get_object_or_404(
        GuestBooking.objects.select_related('listing'),
        pk=pk, user=request.user,
    )
    if not booking.can_be_reviewed:
        messages.info(request, 'You cannot review this booking right now.')
        return redirect('guestaccount:booking_detail', pk=booking.pk)

    if request.method == 'POST':
        try:
            rating = int(request.POST.get('rating') or 5)
        except (TypeError, ValueError):
            rating = 5
        rating = max(1, min(5, rating))

        title = request.POST.get('title', '').strip()
        body = request.POST.get('body', '').strip()

        try:
            from marketplace.models import Review
            Review.objects.update_or_create(
                listing=booking.listing,
                user=request.user,
                defaults={
                    'rating': rating,
                    'title': title,
                    'body': body,
                    'is_published': True,
                },
            )
            _notify(
                organization=booking.organization,
                event='guestaccount.review.created',
                subject=f'New {rating}★ review for {booking.listing.title}',
                body=body or title or '(no comment)',
                guest_booking=booking,
                user=request.user,
            )
            messages.success(request, 'Thanks for your review!')
        except Exception:
            logger.exception('Review creation failed')
            messages.error(request, 'Could not save your review. Please try again.')

        return redirect('guestaccount:booking_detail', pk=booking.pk)

    return render(request, 'guestaccount/booking_review.html', {
        'booking': booking,
        'listing': booking.listing,
    })


# ---------------------------------------------------------------------------
# RECEIPTS (unchanged)
# ---------------------------------------------------------------------------
@login_required
def receipt_list(request):
    if not _require_guest(request):
        return redirect('dashboard')

    receipts = (
        Receipt.objects
        .filter(guest_booking__user=request.user)
        .select_related('guest_booking', 'guest_booking__listing')
        .order_by('-issued_at')
    )
    return render(request, 'guestaccount/receipt_list.html', {'receipts': receipts})


# ---------------------------------------------------------------------------
# PROFILE (unchanged)
# ---------------------------------------------------------------------------
@login_required
def profile(request):
    if not _require_guest(request):
        return redirect('dashboard')

    user = request.user
    profile_obj, _ = GuestProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        user.full_name = request.POST.get('full_name', '').strip()
        user.email = request.POST.get('email', '').strip() or user.email
        user.phone = request.POST.get('phone', '').strip()
        user.save()

        profile_obj.country = request.POST.get('country', '').strip()
        profile_obj.city = request.POST.get('city', '').strip()
        profile_obj.marketing_opt_in = 'marketing_opt_in' in request.POST
        profile_obj.save()

        messages.success(request, 'Profile updated.')
        return redirect('guestaccount:profile')

    return render(request, 'guestaccount/profile.html', {
        'profile': profile_obj,
    })


# ---------------------------------------------------------------------------
# BOOKING STATUS UPDATE (unchanged)
# ---------------------------------------------------------------------------
@login_required
def booking_status_update(request, pk, new_status):
    is_org_member = getattr(request.user, 'is_org_member', False)
    if not _require_guest(request) and not is_org_member:
        return redirect('dashboard')

    booking = get_object_or_404(GuestBooking, pk=pk)

    owns_as_guest = booking.user_id == request.user.id
    owns_as_org = (
        is_org_member
        and booking.organization_id == getattr(request.user, 'organization_id', None)
    )
    if not (owns_as_guest or owns_as_org):
        messages.error(request, 'Access denied.')
        return redirect('guestaccount:home')

    valid = {s[0] for s in GuestBooking.STATUS_CHOICES}
    if new_status not in valid:
        messages.error(request, 'Invalid status.')
        return redirect('guestaccount:booking_detail', pk=booking.pk)

    if new_status == 'cancelled':
        booking.mark_cancelled()
    elif new_status == 'completed':
        booking.mark_completed()
    elif new_status == 'in_progress':
        booking.mark_in_progress()
    elif new_status == 'confirmed':
        booking.mark_confirmed(by_user=request.user if is_org_member else None)
    else:
        booking.status = new_status
        booking.save(update_fields=['status', 'updated_at'])

    messages.success(request, f'Booking is now {new_status}.')
    return redirect('guestaccount:booking_detail', pk=booking.pk)