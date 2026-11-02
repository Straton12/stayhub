# tours/views.py
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Guide, TourBooking, TourPackage, Vehicle


# ============================================================
#  HELPERS
# ============================================================
def _require(request):
    org = getattr(request.user, 'organization', None)
    return bool(org and org.org_type in ('tours', 'mixed')) or \
           getattr(request.user, 'is_superadmin', False)


def _org(request):
    return getattr(request.user, 'organization', None)


def _category(slug):
    try:
        from marketplace.models import ListingCategory
        return ListingCategory.objects.filter(slug=slug).first()
    except Exception:
        return None


def _ensure_listing_for_package(package):
    """Create or update the marketplace listing for a TourPackage."""
    try:
        from marketplace.models import Listing
    except Exception:
        return None

    cat = _category('tours')
    if not cat:
        return None

    defaults = {
        'organization': package.organization,
        'category': cat,
        'source_app': 'tours',
        'source_model': 'TourPackage',
        'source_id': package.id,
        'title': package.name,
        'short_description': package.short_description or (package.description or '')[:280],
        'description': package.description or '',
        'location': package.destination or getattr(package.organization, 'location', '') or '',
        'address': getattr(package.organization, 'address', '') or '',
        'price': package.price_per_person or 0,
        'price_unit': 'per person',
        'max_guests': package.max_travellers or 20,
        'payment_policy': package.payment_policy,
        'deposit_percent': package.deposit_percent or 0,
        'service_fee_percent': package.service_fee_percent or 0,
        'cover_image_url': package.cover_image_url or '',
        'status': 'pending' if package.listing_id is None else package.listing.status,
    }
    listing, _ = Listing.objects.update_or_create(
        source_app='tours', source_model='TourPackage', source_id=package.id,
        defaults=defaults,
    )
    if package.listing_id != listing.id:
        package.listing = listing
        package.save(update_fields=['listing'])
    return listing


def _notify(organization, event, subject, body='', guest_booking=None,
            user=None, email='', phone=''):
    try:
        from notifications.models import NotificationLog
        NotificationLog.objects.create(
            channel='inapp',
            status='sent',
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
        pass


def _departure_is_available(package, travel_date, exclude_booking_id=None):
    """Check no other confirmed/pending booking exists on the same date."""
    if not travel_date:
        return True
    qs = TourBooking.objects.filter(
        package=package,
        travel_date=travel_date,
        status__in=['confirmed', 'pending'],
    )
    if exclude_booking_id:
        qs = qs.exclude(id=exclude_booking_id)
    return not qs.exists()


# ============================================================
#  DASHBOARD
# ============================================================
@login_required
def tours_dashboard(request):
    if not _require(request):
        messages.error(request, 'Tours module not available.')
        return redirect('dashboard')

    org = _org(request)
    today = timezone.now().date()
    month_start = today.replace(day=1)

    packages = TourPackage.objects.filter(organization=org) if org else TourPackage.objects.none()
    bookings = TourBooking.objects.filter(package__organization=org) if org else TourBooking.objects.none()

    revenue_total = bookings.filter(
        status__in=['confirmed', 'completed']
    ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')

    revenue_month = bookings.filter(
        status__in=['confirmed', 'completed'],
        created_at__date__gte=month_start,
    ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')

    outstanding = sum(
        (b.balance for b in bookings.exclude(status__in=['cancelled', 'completed'])
         if b.balance > 0),
        Decimal('0.00'),
    )

    notifications_unread = 0
    try:
        from notifications.models import NotificationLog
        notifications_unread = NotificationLog.objects.filter(
            recipient_organization=org,
        ).count()
    except Exception:
        pass

    return render(request, 'tours/dashboard.html', {
        'packages': packages,
        'bookings': bookings.order_by('-created_at')[:10],
        'packages_count': packages.count(),
        'active_packages_count': packages.filter(is_active=True).count(),
        'bookings_count': bookings.count(),
        'upcoming_departures': bookings.filter(
            travel_date__gte=today,
            status__in=['pending', 'confirmed'],
        ).order_by('travel_date')[:8],
        'guides_count': Guide.objects.filter(organization=org).count() if org else 0,
        'vehicles_count': Vehicle.objects.filter(organization=org).count() if org else 0,
        'revenue_total': revenue_total,
        'revenue_month': revenue_month,
        'outstanding': outstanding,
        'notifications_unread': notifications_unread,
    })


# ============================================================
#  NOTIFICATIONS
# ============================================================
@login_required
def notifications_inbox(request):
    org = _org(request)
    items = []
    try:
        from notifications.models import NotificationLog
        items = NotificationLog.objects.filter(
            recipient_organization=org,
        ).order_by('-created_at')[:200]
    except Exception:
        pass
    return render(request, 'tours/notifications_inbox.html', {
        'items': items,
        'organization': org,
    })


# ============================================================
#  PACKAGES
# ============================================================
@login_required
def package_list(request):
    org = _org(request)
    q = (request.GET.get('q') or '').strip()
    packages = TourPackage.objects.filter(organization=org) if org else TourPackage.objects.none()
    if q:
        packages = packages.filter(
            Q(name__icontains=q) | Q(destination__icontains=q),
        )
    return render(request, 'tours/package_list.html', {
        'packages': packages,
        'q': q,
    })


@login_required
def package_add(request):
    if request.method == 'POST':
        package = TourPackage.objects.create(
            organization=_org(request),
            name=request.POST.get('name', '').strip(),
            package_type=request.POST.get('package_type', 'day_trip'),
            destination=request.POST.get('destination', '').strip(),
            duration_days=request.POST.get('duration_days') or 1,
            price_per_person=request.POST.get('price_per_person') or 0,
            short_description=request.POST.get('short_description', '').strip(),
            description=request.POST.get('description', '').strip(),
            cover_image_url=request.POST.get('cover_image_url', '').strip(),
            highlights=request.POST.get('highlights', '').strip(),
            what_to_bring=request.POST.get('what_to_bring', '').strip(),
            min_travellers=request.POST.get('min_travellers') or 1,
            max_travellers=request.POST.get('max_travellers') or 20,
            pickup_available=(request.POST.get('pickup_available') == 'on'),
            languages=request.POST.get('languages', '').strip(),
            payment_policy=request.POST.get('payment_policy', 'pay_now'),
            deposit_percent=request.POST.get('deposit_percent') or 0,
        )
        _ensure_listing_for_package(package)
        messages.success(request, 'Tour package added and submitted to the marketplace.')
        return redirect('tours_package_list')
    return render(request, 'tours/package_form.html', {'mode': 'create'})


@login_required
def package_edit(request, package_id):
    package = get_object_or_404(
        TourPackage, id=package_id, organization=_org(request),
    )

    if request.method == 'POST':
        package.name = request.POST.get('name', package.name).strip() or package.name
        package.package_type = request.POST.get('package_type', package.package_type)
        package.destination = request.POST.get('destination', package.destination).strip()
        package.duration_days = request.POST.get('duration_days') or package.duration_days
        package.price_per_person = request.POST.get('price_per_person') or package.price_per_person
        package.short_description = request.POST.get('short_description', '').strip()
        package.description = request.POST.get('description', '').strip()
        package.cover_image_url = request.POST.get('cover_image_url', '').strip()
        package.highlights = request.POST.get('highlights', '').strip()
        package.what_to_bring = request.POST.get('what_to_bring', '').strip()
        package.min_travellers = request.POST.get('min_travellers') or 1
        package.max_travellers = request.POST.get('max_travellers') or 20
        package.pickup_available = (request.POST.get('pickup_available') == 'on')
        package.languages = request.POST.get('languages', '').strip()
        package.payment_policy = request.POST.get('payment_policy', package.payment_policy)
        package.deposit_percent = request.POST.get('deposit_percent') or package.deposit_percent
        package.is_active = request.POST.get('is_active') == 'on'
        package.save()

        _ensure_listing_for_package(package)
        messages.success(request, 'Tour package updated and marketplace listing refreshed.')
        return redirect('tours_package_list')

    return render(request, 'tours/package_form.html', {
        'mode': 'edit',
        'package': package,
    })


@login_required
def package_publish_toggle(request, package_id):
    package = get_object_or_404(TourPackage, id=package_id, organization=_org(request))
    if not package.listing_id:
        _ensure_listing_for_package(package)
    if package.listing:
        package.listing.is_active = not package.listing.is_active
        if package.listing.is_active and package.listing.status == 'unpublished':
            package.listing.status = 'approved'
        package.listing.save(update_fields=['is_active', 'status'])
        messages.success(
            request,
            f"Marketplace listing is now {'live' if package.listing.is_active else 'hidden'}.",
        )
    return redirect('tours_package_list')


# ============================================================
#  BOOKINGS
# ============================================================
@login_required
def booking_list(request):
    org = _org(request)
    status = (request.GET.get('status') or '').strip()
    q = (request.GET.get('q') or '').strip()

    bookings = TourBooking.objects.filter(package__organization=org) if org else TourBooking.objects.none()
    if status:
        bookings = bookings.filter(status=status)
    if q:
        bookings = bookings.filter(
            Q(customer_name__icontains=q) |
            Q(customer_email__icontains=q) |
            Q(customer_phone__icontains=q),
        )
    return render(request, 'tours/booking_list.html', {
        'bookings': bookings,
        'status': status,
        'q': q,
    })


@login_required
def booking_add(request):
    org = _org(request)
    packages = TourPackage.objects.filter(organization=org, is_active=True) if org else TourPackage.objects.none()

    if request.method == 'POST':
        package_id = request.POST.get('package')
        package = get_object_or_404(TourPackage, id=package_id, organization=org)

        travel_date_raw = request.POST.get('travel_date', '').strip()
        try:
            travel_date = date.fromisoformat(travel_date_raw)
        except (TypeError, ValueError):
            travel_date = None

        if travel_date and not _departure_is_available(package, travel_date):
            messages.error(request, 'That departure date is already booked. Please pick another.')
            return redirect('tours_booking_add')

        booking = TourBooking.objects.create(
            package=package,
            customer_name=request.POST.get('customer_name', '').strip(),
            customer_email=request.POST.get('customer_email', '').strip(),
            customer_phone=request.POST.get('customer_phone', '').strip(),
            travellers_count=request.POST.get('travellers_count') or 1,
            travel_date=travel_date,
            total_amount=request.POST.get('total_amount') or 0,
            amount_paid=request.POST.get('amount_paid') or 0,
            notes=request.POST.get('notes', '').strip(),
            special_requests=request.POST.get('special_requests', '').strip(),
        )
        _notify(
            organization=org,
            event='tours.booking.created',
            subject=f"New tour booking {booking.reference}",
            body=f"{booking.customer_name} · {package.name} · {booking.travel_date}",
            email=booking.customer_email,
            phone=booking.customer_phone,
        )
        messages.success(request, 'Tour booking created.')
        return redirect('tours_booking_detail', booking_id=booking.id)

    return render(request, 'tours/booking_form.html', {'packages': packages})


@login_required
def booking_detail(request, booking_id):
    booking = get_object_or_404(TourBooking, id=booking_id, package__organization=_org(request))
    guest_booking = booking.guest_booking
    payment_attempts = []
    receipts = []
    if guest_booking:
        payment_attempts = guest_booking.payment_attempts.all()
        receipts = guest_booking.receipts.all()
    return render(request, 'tours/booking_detail.html', {
        'booking': booking,
        'guest_booking': guest_booking,
        'payment_attempts': payment_attempts,
        'receipts': receipts,
    })


@login_required
def booking_edit(request, booking_id):
    booking = get_object_or_404(TourBooking, id=booking_id, package__organization=_org(request))
    packages = TourPackage.objects.filter(organization=_org(request), is_active=True)

    if request.method == 'POST':
        booking.customer_name = request.POST.get('customer_name', booking.customer_name).strip() or booking.customer_name
        booking.customer_email = request.POST.get('customer_email', '').strip()
        booking.customer_phone = request.POST.get('customer_phone', '').strip()
        booking.travellers_count = request.POST.get('travellers_count') or booking.travellers_count
        travel_date_raw = request.POST.get('travel_date', '').strip()
        try:
            booking.travel_date = date.fromisoformat(travel_date_raw)
        except (TypeError, ValueError):
            pass
        booking.total_amount = request.POST.get('total_amount') or booking.total_amount
        booking.amount_paid = request.POST.get('amount_paid') or booking.amount_paid
        booking.notes = request.POST.get('notes', '').strip()
        booking.special_requests = request.POST.get('special_requests', '').strip()
        booking.save()
        messages.success(request, 'Booking updated.')
        return redirect('tours_booking_detail', booking_id=booking.id)

    return render(request, 'tours/booking_form.html', {
        'booking': booking,
        'packages': packages,
    })


@login_required
def booking_status_update(request, booking_id, new_status):
    booking = get_object_or_404(TourBooking, id=booking_id, package__organization=_org(request))
    if new_status not in dict(TourBooking.STATUS):
        messages.error(request, 'Invalid status.')
        return redirect('tours_booking_detail', booking_id=booking.id)
    booking.mark_status(new_status)
    messages.success(request, f'Booking is now {new_status}.')
    return redirect('tours_booking_detail', booking_id=booking.id)


# ============================================================
#  GUIDES
# ============================================================
@login_required
def guide_list(request):
    org = _org(request)
    guides = Guide.objects.filter(organization=org) if org else Guide.objects.none()
    return render(request, 'tours/guide_list.html', {'guides': guides})


@login_required
def guide_add(request):
    if request.method == 'POST':
        Guide.objects.create(
            organization=_org(request),
            name=request.POST.get('name', '').strip(),
            phone=request.POST.get('phone', '').strip(),
            email=request.POST.get('email', '').strip(),
            languages=request.POST.get('languages', '').strip(),
            license_number=request.POST.get('license_number', '').strip(),
            notes=request.POST.get('notes', '').strip(),
            is_active=request.POST.get('is_active') == 'on',
        )
        messages.success(request, 'Guide added.')
        return redirect('tours_guide_list')
    return render(request, 'tours/guide_form.html')


@login_required
def guide_edit(request, guide_id):
    guide = get_object_or_404(Guide, id=guide_id, organization=_org(request))
    if request.method == 'POST':
        guide.name = request.POST.get('name', guide.name).strip() or guide.name
        guide.phone = request.POST.get('phone', '').strip()
        guide.email = request.POST.get('email', '').strip()
        guide.languages = request.POST.get('languages', '').strip()
        guide.license_number = request.POST.get('license_number', '').strip()
        guide.notes = request.POST.get('notes', '').strip()
        guide.is_active = request.POST.get('is_active') == 'on'
        guide.save()
        messages.success(request, 'Guide updated.')
        return redirect('tours_guide_list')
    return render(request, 'tours/guide_form.html', {'guide': guide})


# ============================================================
#  VEHICLES
# ============================================================
@login_required
def vehicle_list(request):
    org = _org(request)
    vehicles = Vehicle.objects.filter(organization=org) if org else Vehicle.objects.none()
    return render(request, 'tours/vehicle_list.html', {'vehicles': vehicles})


@login_required
def vehicle_add(request):
    if request.method == 'POST':
        Vehicle.objects.create(
            organization=_org(request),
            name=request.POST.get('name', '').strip(),
            plate_number=request.POST.get('plate_number', '').strip(),
            capacity=request.POST.get('capacity') or 4,
            vehicle_type=request.POST.get('vehicle_type', '').strip(),
            notes=request.POST.get('notes', '').strip(),
            is_active=request.POST.get('is_active') == 'on',
        )
        messages.success(request, 'Vehicle added.')
        return redirect('tours_vehicle_list')
    return render(request, 'tours/vehicle_form.html')


@login_required
def vehicle_edit(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, id=vehicle_id, organization=_org(request))
    if request.method == 'POST':
        vehicle.name = request.POST.get('name', vehicle.name).strip() or vehicle.name
        vehicle.plate_number = request.POST.get('plate_number', '').strip()
        vehicle.capacity = request.POST.get('capacity') or vehicle.capacity
        vehicle.vehicle_type = request.POST.get('vehicle_type', '').strip()
        vehicle.notes = request.POST.get('notes', '').strip()
        vehicle.is_active = request.POST.get('is_active') == 'on'
        vehicle.save()
        messages.success(request, 'Vehicle updated.')
        return redirect('tours_vehicle_list')
    return render(request, 'tours/vehicle_form.html', {'vehicle': vehicle})