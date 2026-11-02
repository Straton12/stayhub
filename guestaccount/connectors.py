# guestaccount/connectors.py
"""
Connectors that translate a GuestBooking into the corresponding
underlying product row (bnb.Booking, tours.TourBooking, restaurant.Order,
laundry.LaundryOrder) and return (app_label, model_name, object_id).

Each function is defensive: if the corresponding app isn't installed, or
something goes wrong, it returns empty strings and the guest booking
still works with no linked product row.
"""


def _classify(listing):
    """Figure out which source model we're dealing with."""
    return (listing.source_app or '').lower(), (listing.source_model or '').lower()


# ---------------------------------------------------------------------------
# BnB — source_model is 'Property' (no more Unit)
# ---------------------------------------------------------------------------
def create_bnb_booking(guest_booking):
    try:
        from bnb.models import Booking, Property
    except Exception:
        return ('', '', 0)

    _app, model = _classify(guest_booking.listing)
    if model not in ('property', 'unit'):
        return ('', '', 0)

    # Prefer the FK on Property; fall back to source_id lookup.
    prop = None
    try:
        prop = Property.objects.filter(listing=guest_booking.listing).first()
    except Exception:
        prop = None

    if prop is None and guest_booking.listing.source_id:
        try:
            prop = Property.objects.get(pk=guest_booking.listing.source_id)
        except Exception:
            prop = None

    if prop is None:
        return ('', '', 0)

    # Idempotent — one bnb.Booking per GuestBooking
    existing = Booking.objects.filter(guest_booking=guest_booking).first()
    if existing:
        return ('bnb', 'Booking', existing.pk)

    # Ensure a bnb.Guest record exists
    try:
        from bnb.models import Guest
        guest, _ = Guest.objects.get_or_create(
            organization=guest_booking.organization,
            email=guest_booking.customer_email or f'guest-{guest_booking.pk}@placeholder.local',
            defaults={
                'full_name': guest_booking.customer_name,
                'phone': guest_booking.customer_phone,
            },
        )
    except Exception:
        guest = None

    try:
        booking = Booking.objects.create(
            property=prop,
            guest=guest,
            guest_booking=guest_booking,
            guest_name=guest_booking.customer_name,
            guest_email=guest_booking.customer_email,
            guest_phone=guest_booking.customer_phone,
            check_in=guest_booking.start_date,
            check_out=guest_booking.end_date,
            status='pending',
            source='marketplace',
            total_amount=guest_booking.total_amount,
            amount_paid=guest_booking.amount_paid,
            notes=f'Marketplace booking {guest_booking.reference}',
        )
    except Exception:
        return ('', '', 0)

    return ('bnb', 'Booking', booking.pk)


# ---------------------------------------------------------------------------
# Tours
# ---------------------------------------------------------------------------
def create_tour_booking(guest_booking):
    try:
        from tours.models import TourBooking, TourPackage
    except Exception:
        return ('', '', 0)

    _app, model = _classify(guest_booking.listing)
    if model != 'tourpackage':
        return ('', '', 0)

    package = None
    try:
        package = TourPackage.objects.filter(listing=guest_booking.listing).first()
    except Exception:
        package = None
    if package is None and guest_booking.listing.source_id:
        try:
            package = TourPackage.objects.get(pk=guest_booking.listing.source_id)
        except Exception:
            package = None
    if package is None:
        return ('', '', 0)

    existing = TourBooking.objects.filter(guest_booking=guest_booking).first()
    if existing:
        return ('tours', 'TourBooking', existing.pk)

    try:
        booking = TourBooking.objects.create(
            package=package,
            guest_booking=guest_booking,
            customer_name=guest_booking.customer_name,
            customer_email=guest_booking.customer_email,
            customer_phone=guest_booking.customer_phone,
            travellers_count=guest_booking.quantity or 1,
            travel_date=guest_booking.start_date,
            source='marketplace',
            total_amount=guest_booking.total_amount,
            amount_paid=guest_booking.amount_paid,
        )
    except Exception:
        return ('', '', 0)

    return ('tours', 'TourBooking', booking.pk)


# ---------------------------------------------------------------------------
# Restaurant — order
# ---------------------------------------------------------------------------
def create_restaurant_order(guest_booking):
    try:
        from restaurant.models import Order, OrderItem, MenuItem
    except Exception:
        return ('', '', 0)

    _app, model = _classify(guest_booking.listing)
    if model != 'menuitem':
        return ('', '', 0)

    menu_item = None
    try:
        menu_item = MenuItem.objects.filter(listing=guest_booking.listing).first()
    except Exception:
        menu_item = None
    if menu_item is None and guest_booking.listing.source_id:
        try:
            menu_item = MenuItem.objects.get(pk=guest_booking.listing.source_id)
        except Exception:
            menu_item = None
    if menu_item is None:
        return ('', '', 0)

    existing = Order.objects.filter(guest_booking=guest_booking).first()
    if existing:
        return ('restaurant', 'Order', existing.pk)

    try:
        order = Order.objects.create(
            organization=guest_booking.organization,
            listing=guest_booking.listing,
            guest_booking=guest_booking,
            customer_name=guest_booking.customer_name,
            customer_phone=guest_booking.customer_phone,
            customer_address=guest_booking.details.get('delivery_address', ''),
            order_type=guest_booking.details.get('order_type', 'delivery'),
            source='marketplace',
            payment_policy=guest_booking.payment_policy or 'pay_on_delivery',
            subtotal=guest_booking.subtotal,
            total_amount=guest_booking.total_amount,
            amount_paid=guest_booking.amount_paid,
        )
        OrderItem.objects.create(
            order=order,
            menu_item=menu_item,
            name_snapshot=menu_item.name,
            unit_price=guest_booking.unit_price,
            quantity=guest_booking.quantity or 1,
        )
    except Exception:
        return ('', '', 0)

    return ('restaurant', 'Order', order.pk)


# ---------------------------------------------------------------------------
# Laundry
# ---------------------------------------------------------------------------
def create_laundry_order(guest_booking):
    try:
        from laundry.models import LaundryOrder
    except Exception:
        return ('', '', 0)

    _app, model = _classify(guest_booking.listing)
    if model != 'laundryservice':
        return ('', '', 0)

    existing = LaundryOrder.objects.filter(guest_booking=guest_booking).first()
    if existing:
        return ('laundry', 'LaundryOrder', existing.pk)

    try:
        order = LaundryOrder.objects.create(
            organization=guest_booking.organization,
            listing=guest_booking.listing,
            guest_booking=guest_booking,
            customer_name=guest_booking.customer_name,
            customer_phone=guest_booking.customer_phone,
            pickup_address=guest_booking.details.get('pickup_address', ''),
            delivery_address=guest_booking.details.get('delivery_address', ''),
            source='marketplace',
            payment_policy=guest_booking.payment_policy or 'pay_on_delivery',
            total_amount=guest_booking.total_amount,
            amount_paid=guest_booking.amount_paid,
        )
    except Exception:
        return ('', '', 0)

    return ('laundry', 'LaundryOrder', order.pk)


# ---------------------------------------------------------------------------
# Transport — no source model, GuestBooking stands alone
# ---------------------------------------------------------------------------
def create_transport_booking(guest_booking):
    return ('', '', 0)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
CONNECTORS = {
    'stays':     create_bnb_booking,
    'tours':     create_tour_booking,
    'food':      create_restaurant_order,
    'laundry':   create_laundry_order,
    'transport': create_transport_booking,
}


def create_source_row(guest_booking):
    """
    Dispatch to the right connector based on listing category slug.
    Returns (app, model, id). May be ('', '', 0) for categories with no
    underlying product app.
    """
    fn = CONNECTORS.get(guest_booking.listing.category.slug)
    if not fn:
        return ('', '', 0)
    try:
        return fn(guest_booking)
    except Exception:
        return ('', '', 0)