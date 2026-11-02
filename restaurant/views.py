# restaurant/views.py
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    MenuItemForm,
    RecipeLineForm,
    RestaurantProfileForm,
)
from .models import (
    GoodsReceivedLine,
    GoodsReceivedNote,
    MenuItem,
    Order,
    OrderItem,
    PurchaseOrder,
    PurchaseOrderLine,
    Receipt,
    RecipeLine,
    Reservation,
    RestaurantProfile,
    StockItem,
    StockMovement,
    Supplier,
)


# ============================================================
#  HELPERS
# ============================================================
def _require(request):
    org = getattr(request.user, 'organization', None)
    return bool(org and org.org_type in ('restaurant', 'mixed')) or \
           getattr(request.user, 'is_superadmin', False)


def _org(request):
    return getattr(request.user, 'organization', None)


def _category(slug):
    try:
        from marketplace.models import ListingCategory
        return ListingCategory.objects.filter(slug=slug).first()
    except Exception:
        return None


def _get_or_create_profile(org):
    """Return the restaurant profile for org, creating one if missing."""
    profile, _ = RestaurantProfile.objects.get_or_create(
        organization=org,
        defaults={
            'name': org.name,
            'phone': org.phone or '',
            'email': org.email or '',
            'address': org.address or '',
            'location_label': org.location or '',
        },
    )
    return profile



# ============================================================
#  MARKETPLACE SEEDING
# ============================================================
DEFAULT_MARKETPLACE_CATEGORIES = [
    # slug,        name,       icon,   accent,  display_order
    ('food',       'Food',      'utensils', 'amber', 20),
]


def _ensure_default_categories():
    """
    Idempotent — ensures the default ListingCategory rows exist.

    Safe to call on every restaurant request. If the marketplace
    app isn't installed yet, this silently no-ops.
    """
    try:
        from marketplace.models import ListingCategory
        for slug, name, icon, accent, order in DEFAULT_MARKETPLACE_CATEGORIES:
            ListingCategory.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'icon': icon,
                    'accent': accent,
                    'display_order': order,
                },
            )
    except Exception:
        pass


def _ensure_restaurant_listing(profile):
    """
    Create or update the ONE marketplace Listing for this restaurant.

    MenuItems are NOT listings — they are products inside this storefront.

    Called after every profile save, after every publish toggle, and
    whenever the org needs to sync its public state.
    """
    try:
        from marketplace.models import Listing, ListingImage
    except Exception:
        return None

    _ensure_default_categories()

    cat = _category('food')
    if not cat:
        return None

    # ---- Decide status ----
    if not profile.publish_to_marketplace:
        desired_status = 'unpublished'
    elif profile.listing_id is None:
        desired_status = 'approved'  # auto-approved on create
    else:
        desired_status = profile.listing.status or 'approved'

    # ---- Build defaults for the Listing ----
    defaults = {
        'organization':   profile.organization,
        'category':       cat,
        'source_app':     'restaurant',
        'source_model':   'RestaurantProfile',
        'source_id':      profile.id,

        # Public copy
        'title':             profile.name,
        'short_description': profile.short_description or (profile.description or '')[:280],
        'description':       profile.description or '',

        # Cover + gallery
        'cover_image':       profile.cover_image or None,
        'cover_image_url':   '',

        # Location
        'location':          profile.location_label or profile.city or '',
        'address':           profile.address or '',
        'latitude':          profile.latitude,
        'longitude':         profile.longitude,

        # Contact
        'contact_phone':     profile.phone or getattr(profile.organization, 'phone', '') or '',
        'contact_email':     profile.email or getattr(profile.organization, 'email', '') or '',
        'whatsapp':          profile.whatsapp or '',

        # Socials
        'website':           profile.website or '',
        'facebook':          profile.facebook or '',
        'instagram':         profile.instagram or '',
        'twitter':           profile.twitter or '',
        'tiktok':            profile.tiktok or '',
        'youtube':           profile.youtube or '',

        # Commercial
        'price':             0,
        'price_unit':        'menu',
        'min_nights':        1,
        'max_guests':        1,
        'bedrooms':          0,
        'beds':              0,
        'baths':             0,

        # Payment
        'payment_policy':       profile.payment_policy,
        'deposit_percent':      profile.deposit_percent,
        'service_fee_percent':  profile.service_fee_percent or 0,

        # Rules
        'house_rules':          profile.house_rules or '',
        'cancellation_policy':  profile.cancellation_policy,

        # Moderation / visibility
        'status':            desired_status,
        'is_active':         profile.publish_to_marketplace,
        'accepts_bookings':  profile.publish_to_marketplace and profile.is_open_now,
    }

    listing, _created = Listing.objects.update_or_create(
        source_app='restaurant',
        source_model='RestaurantProfile',
        source_id=profile.id,
        defaults=defaults,
    )

    # ---- Attach listing back to profile ----
    if profile.listing_id != listing.id:
        profile.listing = listing
        profile.save(update_fields=['listing'])

    # ---- Refresh the gallery (up to 4 extra images) ----
    ListingImage.objects.filter(listing=listing).delete()
    for i, url in enumerate(profile.gallery_image_urls):
        ListingImage.objects.create(
            listing=listing,
            image_url=url,
            display_order=i * 10,
            caption=f"{profile.name} — image {i + 1}",
        )

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


def _decimal(raw, default='0.00'):
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal(default)


def _int(raw, default=0):
    try:
        return int(raw)
    except Exception:
        return default


def _date(raw, default=None):
    if not raw:
        return default
    try:
        return datetime.fromisoformat(raw).date()
    except Exception:
        return default


# ============================================================
#  DASHBOARD
# ============================================================
@login_required
def restaurant_dashboard(request):
    if not _require(request):
        messages.error(request, 'Restaurant module not available.')
        return redirect('dashboard')

    org = _org(request)
    today = timezone.now().date()
    month_start = today.replace(day=1)

    menu = MenuItem.objects.filter(organization=org) if org else MenuItem.objects.none()
    orders = Order.objects.filter(organization=org) if org else Order.objects.none()
    reservations = Reservation.objects.filter(organization=org) if org else Reservation.objects.none()
    stock = StockItem.objects.filter(organization=org, is_active=True) if org else StockItem.objects.none()

    profile = getattr(org, 'restaurant_profile', None) if org else None

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

    # --- Inventory / procurement KPIs ---
    low_stock_items = [s for s in stock if s.is_low_stock]
    out_of_stock_items = [s for s in stock if s.is_out_of_stock]
    inventory_value = sum((s.stock_value for s in stock), Decimal('0.00'))

    open_pos = PurchaseOrder.objects.filter(
        organization=org, status__in=('draft', 'sent', 'partial'),
    ) if org else PurchaseOrder.objects.none()
    supplier_payables = sum((po.balance for po in open_pos), Decimal('0.00'))

    receipts_today = Receipt.objects.filter(
        organization=org, issued_at__date=today,
    ) if org else Receipt.objects.none()
    receipts_today_total = receipts_today.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    notifications_unread = 0
    try:
        from notifications.models import NotificationLog
        notifications_unread = NotificationLog.objects.filter(
            recipient_organization=org,
        ).count()
    except Exception:
        pass

    return render(request, 'restaurant/dashboard.html', {
        'menu_count': menu.count(),
        'available_menu_count': menu.filter(is_available=True).count(),
        'orders': orders.order_by('-created_at')[:10],
        'orders_count': orders.count(),
        'active_orders': orders.exclude(status__in=['delivered', 'cancelled']).count(),
        'reservations_count': reservations.count(),
        'reservations_today': reservations.filter(reservation_time__date=today).count(),
        'suppliers_count': Supplier.objects.filter(organization=org).count() if org else 0,
        'revenue_total': revenue_total,
        'revenue_month': revenue_month,
        'outstanding': outstanding,
        'notifications_unread': notifications_unread,

        # Marketplace status (from profile)
        'restaurant_profile': profile,
        'profile_published': bool(profile and profile.is_published),
        'profile_publish_status': profile.publish_status if profile else 'unpublished',
        'profile_publish_label': profile.publish_status_label if profile else 'Not published',
        'profile_publish_color': profile.publish_status_color if profile else 'gray',

        # Inventory / procurement
        'low_stock_count': len(low_stock_items),
        'low_stock_items': low_stock_items[:5],
        'out_of_stock_count': len(out_of_stock_items),
        'inventory_value': inventory_value,
        'open_po_count': open_pos.count() if org else 0,
        'supplier_payables': supplier_payables,
        'receipts_today_count': receipts_today.count() if org else 0,
        'receipts_today_total': receipts_today_total,
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
    return render(request, 'restaurant/notifications_inbox.html', {
        'items': items,
        'organization': org,
    })


@login_required
def restaurant_profile(request):
    """
    THE one page where the restaurant is published to the marketplace.
    - GET  → renders form
    - POST → saves the profile, syncs the marketplace Listing
    """
    _ensure_default_categories()

    org = _org(request)
    if not org:
        messages.error(request, 'No organization attached to your account.')
        return redirect('restaurant_dashboard')

    profile = _get_or_create_profile(org)

    if request.method == 'POST':
        form = RestaurantProfileForm(
            request.POST, request.FILES, instance=profile,
        )
        if form.is_valid():
            profile = form.save()

            # Sync to the marketplace!
            listing = _ensure_restaurant_listing(profile)

            if listing:
                if profile.publish_to_marketplace:
                    messages.success(
                        request,
                        f'"{profile.name}" saved and is now LIVE on the marketplace.',
                    )
                else:
                    messages.success(
                        request,
                        f'"{profile.name}" saved (not published to the marketplace).',
                    )
            else:
                messages.warning(
                    request,
                    f'"{profile.name}" saved, but could not sync to the marketplace. '
                    'Please check your marketplace categories.'
                )
            return redirect('restaurant_profile')
    else:
        form = RestaurantProfileForm(instance=profile)

    # Context for the template
    preview_gallery = profile.gallery_image_urls[:4]
    gallery_slots = list(preview_gallery) + [''] * (4 - len(preview_gallery))

    return render(request, 'restaurant/profile.html', {
        'profile':         profile,
        'form':            form,
        'menu_count':      profile.menu_count,
        'live_menu_count': profile.live_menu_count,
        'preview_gallery': preview_gallery,
        'gallery_slots':   gallery_slots,
    })


@login_required
def restaurant_publish_toggle(request):
    """
    Quick publish/unpublish toggle.
    """
    org = _org(request)
    if not org:
        return redirect('restaurant_dashboard')

    profile = _get_or_create_profile(org)
    profile.publish_to_marketplace = not profile.publish_to_marketplace
    profile.save(update_fields=['publish_to_marketplace', 'updated_at'])
    
    # Sync the marketplace listing immediately
    _ensure_restaurant_listing(profile)

    messages.success(
        request,
        f'"{profile.name}" is now {"LIVE" if profile.publish_to_marketplace else "HIDDEN"} '
        f'on the marketplace.',
    )
    return redirect('restaurant_profile')


import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.files.storage import default_storage

@login_required
@require_POST
def restaurant_upload_image(request):
    """
    Ajax endpoint to instantly upload and save a cover or logo image.
    """
    org = _org(request)
    if not org:
        return JsonResponse({'error': 'No organization'}, status=400)

    profile = _get_or_create_profile(org)
    
    image_type = request.POST.get('type')  # 'cover', 'logo', 'gallery'
    file = request.FILES.get('file')

    if not file:
        return JsonResponse({'error': 'No file provided'}, status=400)

    if image_type == 'cover':
        profile.cover_image = file
    elif image_type == 'logo':
        profile.logo = file
    elif image_type == 'gallery':
        # For simplicity, we're overwriting the gallery with an appended list
        # In a production app, you'd handle array logic here.
        # This assumes we just append the URL to the JSON field.
        pass 
    else:
        return JsonResponse({'error': 'Invalid image type'}, status=400)

    profile.save()

    # Trigger the marketplace sync instantly so images appear on the frontend
    _ensure_restaurant_listing(profile)

    return JsonResponse({
        'success': True,
        'url': profile.cover_image.url if image_type == 'cover' and profile.cover_image else (
            profile.logo.url if image_type == 'logo' and profile.logo else ''
        )
    })
    

@login_required
@require_POST
def restaurant_upload_image(request):
    """
    Ajax endpoint to instantly upload and save a cover or logo image.
    """
    org = _org(request)
    if not org:
        return JsonResponse({'error': 'No organization'}, status=400)

    profile = _get_or_create_profile(org)
    
    image_type = request.POST.get('type')  # 'cover', 'logo'
    file = request.FILES.get('file')

    if not file:
        return JsonResponse({'error': 'No file provided'}, status=400)

    if image_type == 'cover':
        profile.cover_image = file
    elif image_type == 'logo':
        profile.logo = file
    else:
        return JsonResponse({'error': 'Invalid image type'}, status=400)

    profile.save()

    # Trigger the marketplace sync instantly so images appear on the frontend
    _ensure_restaurant_listing(profile)

    return JsonResponse({
        'success': True,
        'url': profile.cover_image.url if image_type == 'cover' and profile.cover_image else (
            profile.logo.url if image_type == 'logo' and profile.logo else ''
        )
    }) 
    
    
    



# ============================================================
#  MENU
# ============================================================
@login_required
def menu_list(request):
    org = _org(request)
    q = (request.GET.get('q') or '').strip()
    items = MenuItem.objects.filter(organization=org) if org else MenuItem.objects.none()
    if q:
        items = items.filter(Q(name__icontains=q) | Q(description__icontains=q))
    items = items.prefetch_related('recipe_lines__stock_item').select_related('organization')
    profile = getattr(org, 'restaurant_profile', None) if org else None
    return render(request, 'restaurant/menu_list.html', {
        'items': items,
        'q': q,
        'profile': profile,
    })


@login_required
def menu_add(request):
    org = _org(request)

    if request.method == 'POST':
        form = MenuItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.organization = org
            item.save()
            messages.success(
                request,
                'Menu item added. It appears in your restaurant storefront '
                'when the restaurant is published.'
            )
            return redirect('restaurant_menu_list')
    else:
        form = MenuItemForm()

    return render(request, 'restaurant/menu_form.html', {
        'mode': 'create',
        'form': form,
    })


@login_required
def menu_edit(request, item_id):
    org = _org(request)
    item = get_object_or_404(MenuItem, id=item_id, organization=org)

    if request.method == 'POST':
        form = MenuItemForm(request.POST, instance=item)
        if form.is_valid():
            item = form.save()
            messages.success(request, 'Menu item updated.')
            return redirect('restaurant_menu_list')
    else:
        form = MenuItemForm(instance=item)

    return render(request, 'restaurant/menu_form.html', {
        'mode': 'edit',
        'item': item,
        'form': form,
        'recipe_line_form': RecipeLineForm(organization=org),
        'recipe_lines': item.recipe_lines.select_related('stock_item'),
    })


# ============================================================
#  RECIPE LINES  (bill of materials for a menu item)
# ============================================================
@login_required
def recipe_line_add(request, item_id):
    item = get_object_or_404(MenuItem, id=item_id, organization=_org(request))
    if request.method == 'POST':
        stock_item = get_object_or_404(
            StockItem, id=request.POST.get('stock_item'),
            organization=item.organization,
        )
        quantity = _decimal(request.POST.get('quantity'), '1.00')
        line, created = RecipeLine.objects.update_or_create(
            menu_item=item, stock_item=stock_item,
            defaults={'quantity': quantity, 'notes': request.POST.get('notes', '')},
        )
        messages.success(
            request,
            f"{'Added' if created else 'Updated'} recipe line: "
            f"{quantity} × {stock_item.name}",
        )
    return redirect('restaurant_menu_edit', item_id=item.id)


@login_required
def recipe_line_delete(request, item_id, line_id):
    item = get_object_or_404(MenuItem, id=item_id, organization=_org(request))
    line = get_object_or_404(RecipeLine, id=line_id, menu_item=item)
    line.delete()
    messages.success(request, 'Recipe line removed.')
    return redirect('restaurant_menu_edit', item_id=item.id)


# ============================================================
#  ORDERS
# ============================================================
@login_required
def order_list(request):
    org = _org(request)
    status = (request.GET.get('status') or '').strip()
    q = (request.GET.get('q') or '').strip()

    orders = Order.objects.filter(organization=org) if org else Order.objects.none()
    if status:
        orders = orders.filter(status=status)
    if q:
        orders = orders.filter(
            Q(customer_name__icontains=q) |
            Q(customer_phone__icontains=q),
        )
    return render(request, 'restaurant/order_list.html', {
        'orders': orders,
        'status': status,
        'q': q,
    })


@login_required
def order_add(request):
    org = _org(request)
    menu_items = MenuItem.objects.filter(organization=org, is_available=True) if org else MenuItem.objects.none()

    if request.method == 'POST':
        order = Order.objects.create(
            organization=org,
            customer_name=request.POST.get('customer_name', '').strip(),
            customer_phone=request.POST.get('customer_phone', '').strip(),
            customer_address=request.POST.get('customer_address', '').strip(),
            order_type=request.POST.get('order_type', 'dine_in'),
            payment_policy=request.POST.get('payment_policy', 'pay_on_delivery'),
            delivery_fee=request.POST.get('delivery_fee') or 0,
            special_instructions=request.POST.get('special_instructions', '').strip(),
            notes=request.POST.get('notes', '').strip(),
        )
        # Attach items from POST: item_<id> = qty
        for menu_item in menu_items:
            qty_raw = request.POST.get(f'item_{menu_item.id}')
            if qty_raw:
                try:
                    qty = int(qty_raw)
                except ValueError:
                    qty = 0
                if qty > 0:
                    OrderItem.objects.create(
                        order=order,
                        menu_item=menu_item,
                        name_snapshot=menu_item.name,
                        unit_price=menu_item.price,
                        quantity=qty,
                    )
        order.recalc_totals()
        _notify(
            organization=org,
            event='restaurant.order.created',
            subject=f"New order {order.reference}",
            body=f"{order.customer_name} · {order.get_payment_policy_display()}",
            phone=order.customer_phone,
        )
        messages.success(request, 'Order created.')
        return redirect('restaurant_order_detail', order_id=order.id)

    return render(request, 'restaurant/order_form.html', {'menu_items': menu_items})


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, organization=_org(request))
    guest_booking = order.guest_booking
    payment_attempts = []
    receipts = []
    if guest_booking:
        payment_attempts = guest_booking.payment_attempts.all()
        receipts = guest_booking.receipts.all()

    local_receipts = order.receipts.all()
    stock_consumed = order.stock_movements.filter(movement_type='out')

    return render(request, 'restaurant/order_detail.html', {
        'order': order,
        'items': order.items.all(),
        'guest_booking': guest_booking,
        'payment_attempts': payment_attempts,
        'receipts': receipts,
        'local_receipts': local_receipts,
        'stock_consumed': stock_consumed,
        'can_record_payment': order.balance > 0 and order.status != 'cancelled',
    })


@login_required
def order_edit(request, order_id):
    order = get_object_or_404(Order, id=order_id, organization=_org(request))

    if request.method == 'POST':
        order.customer_name = request.POST.get('customer_name', order.customer_name).strip() or order.customer_name
        order.customer_phone = request.POST.get('customer_phone', '').strip()
        order.customer_address = request.POST.get('customer_address', '').strip()
        order.order_type = request.POST.get('order_type', order.order_type)
        order.payment_policy = request.POST.get('payment_policy', order.payment_policy)
        order.delivery_fee = request.POST.get('delivery_fee') or order.delivery_fee
        order.special_instructions = request.POST.get('special_instructions', '').strip()
        order.notes = request.POST.get('notes', '').strip()
        order.save()
        order.recalc_totals()
        messages.success(request, 'Order updated.')
        return redirect('restaurant_order_detail', order_id=order.id)

    return render(request, 'restaurant/order_form.html', {
        'order': order,
        'menu_items': MenuItem.objects.filter(organization=order.organization, is_available=True),
    })


@login_required
def order_status_update(request, order_id, new_status):
    order = get_object_or_404(Order, id=order_id, organization=_org(request))
    if new_status not in dict(Order.STATUS):
        messages.error(request, 'Invalid status.')
        return redirect('restaurant_order_detail', order_id=order.id)
    order.mark_status(new_status)
    messages.success(request, f'Order is now {new_status}.')
    return redirect('restaurant_order_detail', order_id=order.id)


@login_required
def order_payment_add(request, order_id):
    """
    Record a payment against an order.
    If the order becomes fully paid → auto-issue a Receipt.
    """
    order = get_object_or_404(Order, id=order_id, organization=_org(request))
    if request.method != 'POST':
        return redirect('restaurant_order_detail', order_id=order.id)

    amount = _decimal(request.POST.get('amount'), '0.00')
    method = request.POST.get('method', 'cash')
    reference = request.POST.get('reference', '').strip()

    if amount <= 0:
        messages.error(request, 'Amount must be greater than zero.')
        return redirect('restaurant_order_detail', order_id=order.id)

    receipt = order.record_payment(
        amount=amount,
        method=method,
        reference=reference,
        by_user=request.user,
    )
    if receipt:
        messages.success(
            request,
            f'Payment recorded. Receipt {receipt.number} issued.',
        )
    else:
        messages.success(request, f'Payment of {amount} recorded. Balance: {order.balance}.')
    return redirect('restaurant_order_detail', order_id=order.id)


# ============================================================
#  RESERVATIONS
# ============================================================
@login_required
def reservation_list(request):
    org = _org(request)
    status = (request.GET.get('status') or '').strip()
    items = Reservation.objects.filter(organization=org) if org else Reservation.objects.none()
    if status:
        items = items.filter(status=status)
    return render(request, 'restaurant/reservation_list.html', {
        'items': items,
        'status': status,
    })


@login_required
def reservation_add(request):
    if request.method == 'POST':
        raw_time = request.POST.get('reservation_time', '').strip()
        try:
            reservation_time = datetime.fromisoformat(raw_time)
        except Exception:
            reservation_time = timezone.now()
        reservation = Reservation.objects.create(
            organization=_org(request),
            customer_name=request.POST.get('customer_name', '').strip(),
            customer_phone=request.POST.get('customer_phone', '').strip(),
            customer_email=request.POST.get('customer_email', '').strip(),
            guests=request.POST.get('guests') or 2,
            reservation_time=reservation_time,
            table_preference=request.POST.get('table_preference', '').strip(),
            notes=request.POST.get('notes', '').strip(),
        )
        _notify(
            organization=reservation.organization,
            event='restaurant.reservation.created',
            subject=f"New reservation {reservation.reference}",
            body=f"{reservation.customer_name} · {reservation.guests} guests",
            phone=reservation.customer_phone,
        )
        messages.success(request, 'Reservation created.')
        return redirect('restaurant_reservation_list')
    return render(request, 'restaurant/reservation_form.html')


@login_required
def reservation_detail(request, reservation_id):
    reservation = get_object_or_404(Reservation, id=reservation_id, organization=_org(request))
    return render(request, 'restaurant/reservation_detail.html', {
        'reservation': reservation,
    })


@login_required
def reservation_status_update(request, reservation_id, new_status):
    reservation = get_object_or_404(Reservation, id=reservation_id, organization=_org(request))
    if new_status not in dict(Reservation.STATUS):
        messages.error(request, 'Invalid status.')
        return redirect('restaurant_reservation_detail', reservation_id=reservation.id)
    reservation.mark_status(new_status)
    messages.success(request, f'Reservation is now {new_status}.')
    return redirect('restaurant_reservation_detail', reservation_id=reservation.id)


# ============================================================
#  SUPPLIERS
# ============================================================
@login_required
def supplier_list(request):
    org = _org(request)
    items = Supplier.objects.filter(organization=org) if org else Supplier.objects.none()
    return render(request, 'restaurant/supplier_list.html', {'items': items})


@login_required
def supplier_add(request):
    if request.method == 'POST':
        Supplier.objects.create(
            organization=_org(request),
            name=request.POST.get('name', '').strip(),
            phone=request.POST.get('phone', '').strip(),
            email=request.POST.get('email', '').strip(),
            supplies=request.POST.get('supplies', '').strip(),
            reorder_level=request.POST.get('reorder_level', '').strip(),
            notes=request.POST.get('notes', '').strip(),
        )
        messages.success(request, 'Supplier added.')
        return redirect('restaurant_supplier_list')
    return render(request, 'restaurant/supplier_form.html')


@login_required
def supplier_edit(request, supplier_id):
    supplier = get_object_or_404(Supplier, id=supplier_id, organization=_org(request))
    if request.method == 'POST':
        supplier.name = request.POST.get('name', supplier.name).strip() or supplier.name
        supplier.phone = request.POST.get('phone', '').strip()
        supplier.email = request.POST.get('email', '').strip()
        supplier.supplies = request.POST.get('supplies', '').strip()
        supplier.reorder_level = request.POST.get('reorder_level', '').strip()
        supplier.notes = request.POST.get('notes', '').strip()
        supplier.is_active = request.POST.get('is_active') == 'on'
        supplier.save()
        messages.success(request, 'Supplier updated.')
        return redirect('restaurant_supplier_list')
    return render(request, 'restaurant/supplier_form.html', {'supplier': supplier})


@login_required
def supplier_detail(request, supplier_id):
    supplier = get_object_or_404(Supplier, id=supplier_id, organization=_org(request))
    pos = supplier.purchase_orders.order_by('-order_date')[:20]
    return render(request, 'restaurant/supplier_detail.html', {
        'supplier': supplier,
        'purchase_orders': pos,
    })


# ============================================================
#  STOCK ITEMS
# ============================================================
@login_required
def stock_list(request):
    org = _org(request)
    q = (request.GET.get('q') or '').strip()
    category = (request.GET.get('category') or '').strip()
    only_low = request.GET.get('low') == '1'

    items = StockItem.objects.filter(organization=org) if org else StockItem.objects.none()
    if q:
        items = items.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if category:
        items = items.filter(category=category)

    items = list(items.select_related('organization'))
    if only_low:
        items = [i for i in items if i.is_low_stock]

    total_value = sum((i.stock_value for i in items), Decimal('0.00'))

    return render(request, 'restaurant/stock_list.html', {
        'items': items,
        'q': q,
        'category': category,
        'only_low': only_low,
        'category_choices': StockItem.CATEGORY_CHOICES,
        'total_value': total_value,
        'low_count': sum(1 for i in items if i.is_low_stock),
    })


@login_required
def stock_add(request):
    if request.method == 'POST':
        item = StockItem.objects.create(
            organization=_org(request),
            name=request.POST.get('name', '').strip(),
            sku=request.POST.get('sku', '').strip(),
            category=request.POST.get('category', 'other'),
            unit=request.POST.get('unit', 'pcs'),
            unit_cost=_decimal(request.POST.get('unit_cost'), '0.00'),
            reorder_level=_decimal(request.POST.get('reorder_level'), '0.00'),
            notes=request.POST.get('notes', '').strip(),
        )
        opening_qty = _decimal(request.POST.get('opening_qty'), '0.00')
        if opening_qty > 0:
            StockMovement.objects.create(
                organization=item.organization,
                stock_item=item,
                movement_type='in',
                quantity=opening_qty,
                unit_cost=item.unit_cost,
                reason='Opening stock',
                created_by=request.user,
            )
        messages.success(request, 'Stock item added.')
        return redirect('restaurant_stock_list')
    return render(request, 'restaurant/stock_form.html', {
        'category_choices': StockItem.CATEGORY_CHOICES,
        'unit_choices': StockItem.UNIT_CHOICES,
    })


@login_required
def stock_edit(request, item_id):
    item = get_object_or_404(StockItem, id=item_id, organization=_org(request))
    if request.method == 'POST':
        item.name = request.POST.get('name', item.name).strip() or item.name
        item.sku = request.POST.get('sku', '').strip()
        item.category = request.POST.get('category', item.category)
        item.unit = request.POST.get('unit', item.unit)
        item.unit_cost = _decimal(request.POST.get('unit_cost'), str(item.unit_cost))
        item.reorder_level = _decimal(request.POST.get('reorder_level'), str(item.reorder_level))
        item.notes = request.POST.get('notes', '').strip()
        item.is_active = request.POST.get('is_active') == 'on'
        item.save()
        messages.success(request, 'Stock item updated.')
        return redirect('restaurant_stock_list')
    return render(request, 'restaurant/stock_form.html', {
        'item': item,
        'category_choices': StockItem.CATEGORY_CHOICES,
        'unit_choices': StockItem.UNIT_CHOICES,
    })


@login_required
def stock_detail(request, item_id):
    item = get_object_or_404(StockItem, id=item_id, organization=_org(request))
    movements = item.movements.select_related('created_by', 'order', 'purchase_order')[:100]
    return render(request, 'restaurant/stock_detail.html', {
        'item': item,
        'movements': movements,
    })


# ============================================================
#  STOCK MOVEMENTS
# ============================================================
@login_required
def stock_movement_list(request):
    org = _org(request)
    item_id = request.GET.get('item')
    movement_type = request.GET.get('type')
    date_from = _date(request.GET.get('from'))
    date_to = _date(request.GET.get('to'))

    qs = StockMovement.objects.filter(organization=org) if org else StockMovement.objects.none()
    if item_id:
        qs = qs.filter(stock_item_id=item_id)
    if movement_type:
        qs = qs.filter(movement_type=movement_type)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    return render(request, 'restaurant/stock_movement_list.html', {
        'movements': qs.select_related('stock_item', 'created_by')[:200],
        'items': StockItem.objects.filter(organization=org, is_active=True) if org else StockItem.objects.none(),
        'movement_types': StockMovement.MOVEMENT_TYPE,
        'item_id': item_id,
        'movement_type': movement_type,
        'date_from': date_from,
        'date_to': date_to,
    })


@login_required
def stock_movement_add(request):
    org = _org(request)
    items = StockItem.objects.filter(organization=org, is_active=True) if org else StockItem.objects.none()

    if request.method == 'POST':
        stock_item = get_object_or_404(
            StockItem, id=request.POST.get('stock_item'), organization=org,
        )
        movement_type = request.POST.get('movement_type', 'in')
        quantity = _decimal(request.POST.get('quantity'), '0.00')
        unit_cost = _decimal(request.POST.get('unit_cost'), str(stock_item.unit_cost))
        reason = request.POST.get('reason', '').strip()

        if quantity <= 0:
            messages.error(request, 'Quantity must be greater than zero.')
            return redirect('restaurant_stock_movement_add')

        StockMovement.objects.create(
            organization=org,
            stock_item=stock_item,
            movement_type=movement_type,
            quantity=quantity,
            unit_cost=unit_cost,
            reason=reason,
            created_by=request.user,
        )
        messages.success(
            request,
            f"{movement_type.title()} of {quantity} {stock_item.unit} — {stock_item.name}.",
        )
        return redirect('restaurant_stock_detail', item_id=stock_item.id)

    return render(request, 'restaurant/stock_movement_form.html', {
        'items': items,
        'movement_types': StockMovement.MOVEMENT_TYPE,
        'preselected_item': request.GET.get('item'),
    })


@login_required
def stock_adjust(request, item_id):
    """
    Adjust the stock to the physical count. One signed adjustment movement
    is created; `quantity_signed` on the movement does the sign work.
    """
    item = get_object_or_404(StockItem, id=item_id, organization=_org(request))
    if request.method == 'POST':
        counted = _decimal(request.POST.get('counted'), '0.00')
        current = item.current_stock
        delta = counted - current
        if delta == 0:
            messages.info(request, 'No difference — stock already correct.')
            return redirect('restaurant_stock_detail', item_id=item.id)
        StockMovement.objects.create(
            organization=item.organization,
            stock_item=item,
            movement_type='adjustment',
            quantity=delta,                       # signed on purpose
            unit_cost=item.unit_cost,
            reason=f"Physical count adjustment (was {current})",
            created_by=request.user,
        )
        messages.success(request, f'Stock adjusted by {delta}.')
    return redirect('restaurant_stock_detail', item_id=item.id)


# ============================================================
#  PURCHASE ORDERS
# ============================================================
@login_required
def purchase_order_list(request):
    org = _org(request)
    status = (request.GET.get('status') or '').strip()
    qs = PurchaseOrder.objects.filter(organization=org) if org else PurchaseOrder.objects.none()
    if status:
        qs = qs.filter(status=status)
    return render(request, 'restaurant/po_list.html', {
        'orders': qs.select_related('supplier')[:200],
        'status': status,
        'status_choices': PurchaseOrder.STATUS,
    })


@login_required
def purchase_order_add(request):
    org = _org(request)
    suppliers = Supplier.objects.filter(organization=org, is_active=True) if org else Supplier.objects.none()
    stock_items = StockItem.objects.filter(organization=org, is_active=True) if org else StockItem.objects.none()

    if request.method == 'POST':
        with transaction.atomic():
            po = PurchaseOrder.objects.create(
                organization=org,
                supplier=get_object_or_404(Supplier, id=request.POST.get('supplier'), organization=org),
                expected_date=_date(request.POST.get('expected_date')),
                notes=request.POST.get('notes', '').strip(),
                created_by=request.user,
            )
            for si in stock_items:
                qty_raw = request.POST.get(f'item_{si.id}_qty')
                if not qty_raw:
                    continue
                qty = _decimal(qty_raw, '0.00')
                if qty <= 0:
                    continue
                cost = _decimal(request.POST.get(f'item_{si.id}_cost'), str(si.unit_cost))
                PurchaseOrderLine.objects.create(
                    purchase_order=po,
                    stock_item=si,
                    quantity=qty,
                    unit_cost=cost,
                )
            po.recalc_totals()
            if request.POST.get('send_now') == 'on':
                po.mark_sent()
            _notify(
                organization=org,
                event='restaurant.po.created',
                subject=f'Purchase order {po.reference} created',
                body=f'Supplier: {po.supplier.name} · Total: {po.total_amount}',
            )
        messages.success(request, f'Purchase order {po.reference} created.')
        return redirect('restaurant_po_detail', po_id=po.id)

    return render(request, 'restaurant/po_form.html', {
        'suppliers': suppliers,
        'stock_items': stock_items,
    })


@login_required
def purchase_order_detail(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id, organization=_org(request))
    return render(request, 'restaurant/po_detail.html', {
        'po': po,
        'lines': po.lines.select_related('stock_item'),
        'receipts': po.receipts.order_by('-received_date'),
    })


@login_required
def purchase_order_edit(request, po_id):
    org = _org(request)
    po = get_object_or_404(PurchaseOrder, id=po_id, organization=org)
    if po.status not in ('draft',):
        messages.error(request, 'Only draft POs can be edited.')
        return redirect('restaurant_po_detail', po_id=po.id)

    stock_items = StockItem.objects.filter(organization=org, is_active=True)
    if request.method == 'POST':
        with transaction.atomic():
            po.expected_date = _date(request.POST.get('expected_date'), po.expected_date)
            po.notes = request.POST.get('notes', po.notes).strip()
            po.save()
            po.lines.all().delete()
            for si in stock_items:
                qty_raw = request.POST.get(f'item_{si.id}_qty')
                if not qty_raw:
                    continue
                qty = _decimal(qty_raw, '0.00')
                if qty <= 0:
                    continue
                cost = _decimal(request.POST.get(f'item_{si.id}_cost'), str(si.unit_cost))
                PurchaseOrderLine.objects.create(
                    purchase_order=po, stock_item=si,
                    quantity=qty, unit_cost=cost,
                )
            po.recalc_totals()
        messages.success(request, 'Purchase order updated.')
        return redirect('restaurant_po_detail', po_id=po.id)

    return render(request, 'restaurant/po_form.html', {
        'po': po,
        'suppliers': Supplier.objects.filter(organization=org, is_active=True),
        'stock_items': stock_items,
        'lines_by_item': {l.stock_item_id: l for l in po.lines.all()},
    })


@login_required
def purchase_order_send(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id, organization=_org(request))
    if po.status != 'draft':
        messages.error(request, 'Only drafts can be sent.')
        return redirect('restaurant_po_detail', po_id=po.id)
    po.mark_sent()
    messages.success(request, f'{po.reference} sent to {po.supplier.name}.')
    return redirect('restaurant_po_detail', po_id=po.id)


@login_required
def purchase_order_cancel(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id, organization=_org(request))
    if po.status in ('received',):
        messages.error(request, 'Received POs cannot be cancelled.')
        return redirect('restaurant_po_detail', po_id=po.id)
    po.mark_cancelled()
    messages.success(request, f'{po.reference} cancelled.')
    return redirect('restaurant_po_detail', po_id=po.id)


@login_required
def purchase_order_pay(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id, organization=_org(request))
    if request.method == 'POST':
        amount = _decimal(request.POST.get('amount'), '0.00')
        if amount <= 0:
            messages.error(request, 'Amount must be greater than zero.')
            return redirect('restaurant_po_detail', po_id=po.id)
        po.mark_paid(amount)
        messages.success(request, f'Payment of {amount} recorded against {po.reference}.')
    return redirect('restaurant_po_detail', po_id=po.id)


# ============================================================
#  GOODS RECEIVED NOTES (delivery receipts)
# ============================================================
@login_required
def grn_add(request, po_id):
    org = _org(request)
    po = get_object_or_404(PurchaseOrder, id=po_id, organization=org)
    if po.status not in ('sent', 'partial'):
        messages.error(request, 'Only sent or partially-received POs can be received.')
        return redirect('restaurant_po_detail', po_id=po.id)

    lines = po.lines.select_related('stock_item')

    if request.method == 'POST':
        with transaction.atomic():
            grn = GoodsReceivedNote.objects.create(
                purchase_order=po,
                received_date=_date(request.POST.get('received_date'), timezone.now().date()),
                notes=request.POST.get('notes', '').strip(),
                received_by=request.user,
            )
            any_applied = False
            for line in lines:
                qty_raw = request.POST.get(f'line_{line.id}')
                if not qty_raw:
                    continue
                qty = _decimal(qty_raw, '0.00')
                if qty <= 0:
                    continue
                if qty > line.outstanding_quantity:
                    qty = line.outstanding_quantity
                grl = GoodsReceivedLine.objects.create(
                    grn=grn,
                    purchase_order_line=line,
                    quantity_received=qty,
                )
                grl.apply(created_by=request.user)
                any_applied = True

            if not any_applied:
                grn.delete()
                messages.error(request, 'No quantities entered — GRN discarded.')
                return redirect('restaurant_po_detail', po_id=po.id)

            po.refresh_status_from_lines()
            _notify(
                organization=org,
                event='restaurant.po.received',
                subject=f'{grn.reference} received for {po.reference}',
                body=f'Total value: {grn.total_value}',
            )
        messages.success(request, f'Goods received — {grn.reference}.')
        return redirect('restaurant_po_detail', po_id=po.id)

    return render(request, 'restaurant/grn_form.html', {
        'po': po,
        'lines': lines,
    })


@login_required
def grn_list(request):
    org = _org(request)
    qs = GoodsReceivedNote.objects.filter(
        purchase_order__organization=org,
    ) if org else GoodsReceivedNote.objects.none()
    return render(request, 'restaurant/grn_list.html', {
        'receipts': qs.select_related('purchase_order', 'purchase_order__supplier')[:200],
    })


@login_required
def grn_detail(request, grn_id):
    grn = get_object_or_404(
        GoodsReceivedNote, id=grn_id,
        purchase_order__organization=_org(request),
    )
    return render(request, 'restaurant/grn_detail.html', {
        'grn': grn,
        'lines': grn.lines.select_related('purchase_order_line__stock_item'),
    })


# ============================================================
#  RECEIPTS
# ============================================================
@login_required
def receipt_list(request):
    org = _org(request)
    q = (request.GET.get('q') or '').strip()
    qs = Receipt.objects.filter(organization=org) if org else Receipt.objects.none()
    if q:
        qs = qs.filter(
            Q(number__icontains=q) |
            Q(customer_name__icontains=q) |
            Q(reference__icontains=q),
        )
    return render(request, 'restaurant/receipt_list.html', {
        'receipts': qs.select_related('order')[:200],
        'q': q,
    })


@login_required
def receipt_detail(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id, organization=_org(request))
    return render(request, 'restaurant/receipt_detail.html', {
        'receipt': receipt,
        'order': receipt.order,
        'items': receipt.order.items.all(),
    })


@login_required
def receipt_print(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id, organization=_org(request))
    return render(request, 'restaurant/receipt_print.html', {
        'receipt': receipt,
        'order': receipt.order,
        'items': receipt.order.items.all(),
    })


# ============================================================
#  REPORTS
# ============================================================
@login_required
def reports_dashboard(request):
    org = _org(request)
    today = timezone.now().date()
    start = _date(request.GET.get('from'), today.replace(day=1))
    end = _date(request.GET.get('to'), today)

    orders = Order.objects.filter(
        organization=org,
        created_at__date__gte=start,
        created_at__date__lte=end,
    ) if org else Order.objects.none()

    delivered = orders.filter(status='delivered')
    revenue = delivered.aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')
    order_count = orders.count()
    avg_order = (revenue / order_count) if order_count else Decimal('0.00')

    top_items = (
        OrderItem.objects
        .filter(order__in=delivered)
        .values('name_snapshot')
        .annotate(
            total_qty=Sum('quantity'),
            total_revenue=Sum(F('unit_price') * F('quantity')),
        )
        .order_by('-total_qty')[:10]
    )

    pos = PurchaseOrder.objects.filter(
        organization=org,
        order_date__gte=start,
        order_date__lte=end,
    ) if org else PurchaseOrder.objects.none()
    purchases = pos.aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')

    return render(request, 'restaurant/reports.html', {
        'start': start,
        'end': end,
        'revenue': revenue,
        'purchases': purchases,
        'order_count': order_count,
        'avg_order': avg_order,
        'top_items': top_items,
        'gross_margin': revenue - purchases,
    })


# ============================================================
#  AJAX HELPERS
# ============================================================
@login_required
def api_stock_levels(request):
    """
    Return current stock levels for a list of menu items so the
    order form can flag out-of-stock items live.
    """
    org = _org(request)
    item_ids = request.GET.getlist('ids[]')
    data = []
    qs = MenuItem.objects.filter(
        organization=org, id__in=item_ids,
    ) if org and item_ids else MenuItem.objects.none()
    for item in qs:
        data.append({
            'id': item.id,
            'in_stock': item.is_in_stock(1),
            'recipe': [
                {
                    'name': l.stock_item.name,
                    'needed': str(l.quantity),
                    'available': str(l.stock_item.current_stock),
                }
                for l in item.recipe_lines.select_related('stock_item')
            ],
        })
    return JsonResponse({'items': data})