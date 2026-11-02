# laundry/views.py
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import LaundryService, LaundryOrder, LaundrySupply


# ============================================================
#  HELPERS
# ============================================================
def _require(request):
    org = getattr(request.user, 'organization', None)
    return bool(org and org.org_type in ('laundry', 'mixed')) or getattr(request.user, 'is_superadmin', False)


def _org(request):
    return getattr(request.user, 'organization', None)


def _category(slug):
    try:
        from marketplace.models import ListingCategory
        return ListingCategory.objects.filter(slug=slug).first()
    except Exception:
        return None


def _ensure_listing_for_service(service):
    """Create or update the marketplace listing for a LaundryService."""
    try:
        from marketplace.models import Listing
    except Exception:
        return None

    cat = _category('laundry')
    if not cat:
        return None

    defaults = {
        'organization': service.organization,
        'category': cat,
        'source_app': 'laundry',
        'source_model': 'LaundryService',
        'source_id': service.id,
        'title': service.name,
        'short_description': service.short_description or (service.description or '')[:280],
        'description': service.description or '',
        'location': getattr(service.organization, 'location', '') or '',
        'address': getattr(service.organization, 'address', '') or '',
        'price': service.price or 0,
        'price_unit': service.get_price_unit_display().lower(),
        'payment_policy': service.payment_policy,
        'service_fee_percent': service.service_fee_percent or 0,
        'cover_image_url': service.cover_image_url or '',
        'status': 'pending' if service.listing_id is None else service.listing.status,
    }
    listing, _ = Listing.objects.update_or_create(
        source_app='laundry', source_model='LaundryService', source_id=service.id,
        defaults=defaults,
    )
    if service.listing_id != listing.id:
        service.listing = listing
        service.save(update_fields=['listing'])
    return listing


def _notify(organization, event, subject, body='', guest_booking=None,
            user=None, phone=''):
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
            to_phone=phone,
        )
    except Exception:
        pass


# ============================================================
#  DASHBOARD
# ============================================================
@login_required
def laundry_dashboard(request):
    if not _require(request):
        messages.error(request, 'Laundry module not available.')
        return redirect('dashboard')

    org = _org(request)
    today = timezone.now().date()
    month_start = today.replace(day=1)

    services = LaundryService.objects.filter(organization=org) if org else LaundryService.objects.none()
    orders = LaundryOrder.objects.filter(organization=org) if org else LaundryOrder.objects.none()

    revenue_total = orders.filter(
        status='delivered'
    ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')

    revenue_month = orders.filter(
        status='delivered',
        created_at__date__gte=month_start,
    ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')

    outstanding = sum(
        (o.balance for o in orders.exclude(status__in=['cancelled', 'delivered'])
         if o.balance > 0),
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

    return render(request, 'laundry/dashboard.html', {
        'services_count': services.count(),
        'active_services': services.filter(is_active=True).count(),
        'orders': orders.order_by('-created_at')[:10],
        'orders_count': orders.count(),
        'active_orders': orders.exclude(status__in=['delivered', 'cancelled']).count(),
        'supplies_count': LaundrySupply.objects.filter(organization=org).count() if org else 0,
        'revenue_total': revenue_total,
        'revenue_month': revenue_month,
        'outstanding': outstanding,
        'notifications_unread': notifications_unread,
    })


# ============================================================
#  NOTIFICATIONS INBOX
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
    return render(request, 'laundry/notifications_inbox.html', {
        'items': items,
        'organization': org,
    })


# ============================================================
#  SERVICES
# ============================================================
@login_required
def service_list(request):
    org = _org(request)
    q = (request.GET.get('q') or '').strip()
    items = LaundryService.objects.filter(organization=org) if org else LaundryService.objects.none()
    if q:
        items = items.filter(Q(name__icontains=q) | Q(description__icontains=q))
    return render(request, 'laundry/service_list.html', {
        'items': items,
        'q': q,
    })


@login_required
def service_add(request):
    if request.method == 'POST':
        service = LaundryService.objects.create(
            organization=_org(request),
            name=request.POST.get('name', '').strip(),
            service_type=request.POST.get('service_type', 'wash_fold'),
            price=request.POST.get('price') or 0,
            price_unit=request.POST.get('price_unit', 'per_kg'),
            short_description=request.POST.get('short_description', '').strip(),
            description=request.POST.get('description', '').strip(),
            cover_image_url=request.POST.get('cover_image_url', '').strip(),
            turnaround_hours=request.POST.get('turnaround_hours') or 24,
            pickup_available=(request.POST.get('pickup_available') == 'on'),
            delivery_available=(request.POST.get('delivery_available') == 'on'),
            same_day=(request.POST.get('same_day') == 'on'),
            payment_policy=request.POST.get('payment_policy', 'pay_on_delivery'),
            is_active=(request.POST.get('is_active') == 'on'),
        )
        _ensure_listing_for_service(service)
        messages.success(request, 'Service added and submitted to the marketplace.')
        return redirect('laundry_service_list')
    return render(request, 'laundry/service_form.html', {'mode': 'create'})


@login_required
def service_edit(request, service_id):
    service = get_object_or_404(
        LaundryService, id=service_id, organization=_org(request),
    )

    if request.method == 'POST':
        service.name = request.POST.get('name', service.name).strip() or service.name
        service.service_type = request.POST.get('service_type', service.service_type)
        service.price = request.POST.get('price') or service.price
        service.price_unit = request.POST.get('price_unit', service.price_unit)
        service.short_description = request.POST.get('short_description', '').strip()
        service.description = request.POST.get('description', '').strip()
        service.cover_image_url = request.POST.get('cover_image_url', '').strip()
        service.turnaround_hours = request.POST.get('turnaround_hours') or 24
        service.pickup_available = (request.POST.get('pickup_available') == 'on')
        service.delivery_available = (request.POST.get('delivery_available') == 'on')
        service.same_day = (request.POST.get('same_day') == 'on')
        service.payment_policy = request.POST.get('payment_policy', service.payment_policy)
        service.is_active = (request.POST.get('is_active') == 'on')
        service.save()

        _ensure_listing_for_service(service)
        messages.success(request, 'Service updated and marketplace listing refreshed.')
        return redirect('laundry_service_list')

    return render(request, 'laundry/service_form.html', {
        'mode': 'edit',
        'service': service,
    })


@login_required
def service_publish_toggle(request, service_id):
    service = get_object_or_404(LaundryService, id=service_id, organization=_org(request))
    if not service.listing_id:
        _ensure_listing_for_service(service)
    if service.listing:
        service.listing.is_active = not service.listing.is_active
        if service.listing.is_active and service.listing.status == 'unpublished':
            service.listing.status = 'approved'
        service.listing.save(update_fields=['is_active', 'status'])
        messages.success(
            request,
            f"Marketplace listing is now {'live' if service.listing.is_active else 'hidden'}.",
        )
    return redirect('laundry_service_list')


# ============================================================
#  ORDERS
# ============================================================
@login_required
def order_list(request):
    org = _org(request)
    status = (request.GET.get('status') or '').strip()
    q = (request.GET.get('q') or '').strip()

    orders = LaundryOrder.objects.filter(organization=org) if org else LaundryOrder.objects.none()
    if status:
        orders = orders.filter(status=status)
    if q:
        orders = orders.filter(
            Q(customer_name__icontains=q) |
            Q(customer_phone__icontains=q) |
            Q(item_description__icontains=q)
        )
    return render(request, 'laundry/order_list.html', {
        'orders': orders,
        'status': status,
        'q': q,
    })


@login_required
def order_add(request):
    org = _org(request)
    services = LaundryService.objects.filter(organization=org, is_active=True) if org else LaundryService.objects.none()

    if request.method == 'POST':
        order = LaundryOrder.objects.create(
            organization=org,
            service_id=request.POST.get('service') or None,
            customer_name=request.POST.get('customer_name', '').strip(),
            customer_phone=request.POST.get('customer_phone', '').strip(),
            pickup_address=request.POST.get('pickup_address', '').strip(),
            delivery_address=request.POST.get('delivery_address', '').strip(),
            item_description=request.POST.get('item_description', '').strip(),
            quantity=request.POST.get('quantity') or 1,
            unit_price=request.POST.get('unit_price') or 0,
            total_amount=request.POST.get('total_amount') or 0,
            amount_paid=request.POST.get('amount_paid') or 0,
            payment_policy=request.POST.get('payment_policy', 'pay_on_delivery'),
            notes=request.POST.get('notes', '').strip(),
        )
        _notify(
            organization=org,
            event='laundry.order.created',
            subject=f"New laundry order {order.reference}",
            body=f"{order.customer_name} · {order.get_payment_policy_display()}",
            phone=order.customer_phone,
        )
        messages.success(request, 'Laundry order created.')
        return redirect('laundry_order_list')

    return render(request, 'laundry/order_form.html', {'services': services})


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(LaundryOrder, id=order_id, organization=_org(request))
    guest_booking = order.guest_booking
    payment_attempts = []
    receipts = []
    if guest_booking:
        payment_attempts = guest_booking.payment_attempts.all()
        receipts = guest_booking.receipts.all()
    return render(request, 'laundry/order_detail.html', {
        'order': order,
        'guest_booking': guest_booking,
        'payment_attempts': payment_attempts,
        'receipts': receipts,
    })


@login_required
def order_edit(request, order_id):
    order = get_object_or_404(LaundryOrder, id=order_id, organization=_org(request))

    if request.method == 'POST':
        order.customer_name = request.POST.get('customer_name', order.customer_name).strip() or order.customer_name
        order.customer_phone = request.POST.get('customer_phone', '').strip()
        order.pickup_address = request.POST.get('pickup_address', '').strip()
        order.delivery_address = request.POST.get('delivery_address', '').strip()
        order.item_description = request.POST.get('item_description', '').strip()
        order.quantity = request.POST.get('quantity') or order.quantity
        order.unit_price = request.POST.get('unit_price') or order.unit_price
        order.total_amount = request.POST.get('total_amount') or order.total_amount
        order.amount_paid = request.POST.get('amount_paid') or order.amount_paid
        order.payment_policy = request.POST.get('payment_policy', order.payment_policy)
        order.notes = request.POST.get('notes', '').strip()
        order.save()
        messages.success(request, 'Order updated.')
        return redirect('laundry_order_detail', order_id=order.id)

    return render(request, 'laundry/order_form.html', {'order': order})


@login_required
def order_status_update(request, order_id, new_status):
    order = get_object_or_404(LaundryOrder, id=order_id, organization=_org(request))
    if new_status not in dict(LaundryOrder.STATUS):
        messages.error(request, 'Invalid status.')
        return redirect('laundry_order_detail', order_id=order.id)
    order.mark_status(new_status)
    messages.success(request, f'Order is now {new_status}.')
    return redirect('laundry_order_detail', order_id=order.id)


# ============================================================
#  SUPPLIES
# ============================================================
@login_required
def supply_list(request):
    org = _org(request)
    items = LaundrySupply.objects.filter(organization=org) if org else LaundrySupply.objects.none()
    low_stock = [s for s in items if s.quantity <= s.reorder_level]
    return render(request, 'laundry/supply_list.html', {
        'items': items,
        'low_stock': low_stock,
    })


@login_required
def supply_add(request):
    if request.method == 'POST':
        LaundrySupply.objects.create(
            organization=_org(request),
            name=request.POST.get('name', '').strip(),
            quantity=request.POST.get('quantity') or 0,
            unit=request.POST.get('unit', 'pcs'),
            reorder_level=request.POST.get('reorder_level') or 0,
            notes=request.POST.get('notes', '').strip(),
        )
        messages.success(request, 'Supply added.')
        return redirect('laundry_supply_list')
    return render(request, 'laundry/supply_form.html')


@login_required
def supply_edit(request, supply_id):
    supply = get_object_or_404(LaundrySupply, id=supply_id, organization=_org(request))
    if request.method == 'POST':
        supply.name = request.POST.get('name', supply.name).strip() or supply.name
        supply.quantity = request.POST.get('quantity') or supply.quantity
        supply.unit = request.POST.get('unit', supply.unit)
        supply.reorder_level = request.POST.get('reorder_level') or supply.reorder_level
        supply.notes = request.POST.get('notes', '').strip()
        supply.save()
        messages.success(request, 'Supply updated.')
        return redirect('laundry_supply_list')
    return render(request, 'laundry/supply_form.html', {'supply': supply})