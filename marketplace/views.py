# marketplace/views.py

from decimal import Decimal
from types import SimpleNamespace

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Exists, OuterRef, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import ListingCategoryForm, ListingForm, ListingImageFormSet
from .models import (
    Listing, ListingAvailabilityBlock, ListingCategory,
    MAX_GALLERY_IMAGES, Review, Wishlist,
)
from .publishing import approve, reject, unpublish


# ===========================================================================
# HELPERS
# ===========================================================================
def _require_org_admin(request):
    user = request.user
    if not user.is_authenticated:
        return None
    if getattr(user, 'is_superadmin', False):
        return getattr(user, 'organization', None)
    if getattr(user, 'is_orgadmin', False) or getattr(user, 'role', '') == 'staff':
        return getattr(user, 'organization', None)
    return None


def _is_guest(user):
    return user.is_authenticated and getattr(user, 'is_guest', False)


def _listing_owner_or_super(user, listing):
    if getattr(user, 'is_superadmin', False):
        return True
    org = getattr(user, 'organization', None)
    return bool(org and listing.organization_id == org.id)


def _release_expired_blocks():
    """
    Cheap lazy sweep: mark any pending/confirmed availability block whose
    end_date has passed as 'released' so listings become bookable again.

    Runs once per relevant page load. Safe to call often — it's a single
    UPDATE with an indexed filter.
    """
    today = timezone.now().date()
    try:
        ListingAvailabilityBlock.objects.filter(
            status__in=['pending', 'confirmed'],
            end_date__lte=today,
        ).update(status='released')
    except Exception:
        pass


def _annotate_blocked_now(qs):
    """Add is_blocked_now=True when a listing is currently booked."""
    today = timezone.now().date()
    active_blocks = ListingAvailabilityBlock.objects.filter(
        listing=OuterRef('pk'),
        status__in=['pending', 'confirmed'],
        start_date__lte=today,
        end_date__gt=today,
    )
    return qs.annotate(is_blocked_now=Exists(active_blocks))


def _annotate_bnb_metrics(qs):
    """
    Enrich a Listing queryset with B&B-specific counters pulled from the
    linked ``bnb.Property``. Every annotation is optional — the template
    renders fine with ``|default:0`` if the ``bnb`` app isn't installed.

    Adds:
      • bnb_review_count      — total bnb.Review rows for this property
      • bnb_open_maintenance  — bnb.MaintenanceRequest where status != 'resolved'
      • bnb_staff_count       — bnb.StaffMember rows assigned to the property
      • bnb_is_active         — 1 if the linked bnb.Property is active
    """
    try:
        from django.apps import apps
        apps.get_app_config('bnb')
    except Exception:
        return qs

    try:
        return qs.annotate(
            bnb_review_count=Count(
                'bnb_property__reviews',
                filter=Q(bnb_property__reviews__isnull=False),
                distinct=True,
            ),
            bnb_open_maintenance=Count(
                'bnb_property__maintenance',
                filter=~Q(bnb_property__maintenance__status='resolved'),
                distinct=True,
            ),
            bnb_staff_count=Count(
                'bnb_property__staff',
                distinct=True,
            ),
            bnb_is_active=Count(
                'bnb_property__is_active',
                filter=Q(bnb_property__is_active=True),
                distinct=True,
            ),
        )
    except Exception:
        # Reverse accessor mismatch — degrade silently rather than 500.
        return qs


def _user_wishlist_ids(user):
    """Return the set of listing PKs saved by this guest (empty for others)."""
    if not _is_guest(user):
        return set()
    return set(
        Wishlist.objects
        .filter(user=user)
        .values_list('listing_id', flat=True)
    )


# ===========================================================================
# PUBLIC VIEWS
# ===========================================================================
def home(request):
    _release_expired_blocks()

    categories = ListingCategory.objects.all().order_by('display_order', 'name')

    # ----- Featured (8 most recent) -----
    featured_qs = (
        Listing.objects
        .filter(status='approved', is_active=True)
        .select_related('category', 'organization')
        .prefetch_related('images')
        .order_by('-approved_at', '-created_at')
    )
    featured_qs = _annotate_blocked_now(featured_qs)
    featured_qs = _annotate_bnb_metrics(featured_qs)
    featured = list(featured_qs[:8])

    # ----- Popular (most-booked) -----
    popular_qs = (
        Listing.objects
        .filter(status='approved', is_active=True)
        .select_related('category', 'organization')
        .prefetch_related('images')
        .order_by('-booking_count', '-approved_at')
    )
    popular_qs = _annotate_blocked_now(popular_qs)
    popular_qs = _annotate_bnb_metrics(popular_qs)
    popular = list(popular_qs[:4])

    # ----- Popular destinations -----
    locations_qs = (
        Listing.objects
        .filter(status='approved', is_active=True)
        .exclude(location__isnull=True)
        .exclude(location='')
        .values('location')
        .annotate(count=Count('id'))
        .order_by('-count', 'location')[:6]
    )
    popular_locations = []
    for row in locations_qs:
        sample = (
            Listing.objects
            .filter(status='approved', is_active=True, location=row['location'])
            .only('cover_image', 'cover_image_url')
            .first()
        )
        cover = ''
        if sample:
            if sample.cover_image:
                cover = sample.cover_image.url
            elif sample.cover_image_url:
                cover = sample.cover_image_url
        popular_locations.append({
            'name': row['location'],
            'count': row['count'],
            'image': cover,
        })

    return render(request, 'marketplace/home.html', {
        'categories': categories,
        'featured': featured,
        'popular': popular,
        'popular_locations': popular_locations,
        'total_listings': Listing.objects.filter(
            status='approved', is_active=True,
        ).count(),
        'user_wishlist_ids': _user_wishlist_ids(request.user),
    })


def category_page(request, slug):
    _release_expired_blocks()

    category = get_object_or_404(ListingCategory, slug=slug)

    listings = (
        Listing.objects
        .filter(status='approved', is_active=True, category=category)
        .select_related('organization', 'category')
        .prefetch_related('images')
    )

    q = request.GET.get('q', '').strip()
    location = request.GET.get('location', '').strip()
    max_price = request.GET.get('max_price', '').strip()

    if q:
        listings = listings.filter(
            Q(title__icontains=q) |
            Q(short_description__icontains=q) |
            Q(description__icontains=q)
        )
    if location:
        listings = listings.filter(location__icontains=location)
    if max_price:
        try:
            listings = listings.filter(price__lte=Decimal(max_price))
        except (ValueError, ArithmeticError):
            pass

    listings = _annotate_blocked_now(listings)
    listings = _annotate_bnb_metrics(listings)
    listings = listings.order_by('-approved_at')

    paginator = Paginator(listings, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'marketplace/category.html', {
        'category': category,
        'listings': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'q': q,
        'location': location,
        'max_price': max_price,
        'user_wishlist_ids': _user_wishlist_ids(request.user),
    })


def search(request):
    _release_expired_blocks()

    q = request.GET.get('q', '').strip()
    location = request.GET.get('location', '').strip()
    category_slug = request.GET.get('category', '').strip()

    listings = (
        Listing.objects
        .filter(status='approved', is_active=True)
        .select_related('category', 'organization')
        .prefetch_related('images')
    )

    if q:
        listings = listings.filter(
            Q(title__icontains=q) |
            Q(short_description__icontains=q) |
            Q(description__icontains=q) |
            Q(location__icontains=q)
        )
    if location:
        listings = listings.filter(location__icontains=location)
    if category_slug:
        listings = listings.filter(category__slug=category_slug)

    listings = listings.order_by('-approved_at')

    # Radius filter — only materialise into a list when we must
    lat = request.GET.get('lat', '').strip()
    lng = request.GET.get('lng', '').strip()
    radius = request.GET.get('radius', '').strip()

    radius_applied = False
    if lat and lng and radius:
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            r_km = float(radius)
            filtered = []
            for item in listings:
                d = item.distance_from(lat_f, lng_f)
                if d is not None and d <= r_km:
                    filtered.append(item)
            listings = filtered
            radius_applied = True
        except (ValueError, TypeError):
            pass

    # Annotate only when we still have a queryset
    if not radius_applied:
        listings = _annotate_blocked_now(listings)
        listings = _annotate_bnb_metrics(listings)

    # Paginate (radius filter returns a list — skip pagination for it)
    if not radius_applied and hasattr(listings, 'count'):
        paginator = Paginator(listings, 12)
        page_obj = paginator.get_page(request.GET.get('page'))
        listings_page = page_obj.object_list
    else:
        paginator = None
        page_obj = None
        listings_page = listings

    return render(request, 'marketplace/search.html', {
        'listings': listings_page,
        'page_obj': page_obj,
        'paginator': paginator,
        'q': q,
        'location': location,
        'category_slug': category_slug,
        'categories': ListingCategory.objects.all(),
        'lat': lat, 'lng': lng, 'radius': radius,
        'user_wishlist_ids': _user_wishlist_ids(request.user),
    })


def listing_detail(request, slug):
    _release_expired_blocks()

    listing = get_object_or_404(
        Listing.objects
        .select_related('category', 'organization')
        .prefetch_related('images'),
        slug=slug,
    )

    if not listing.is_public and not _listing_owner_or_super(request.user, listing):
        messages.error(request, 'This listing is not available.')
        return redirect('marketplace:home')

    # View counter (fire-and-forget — never fail the page for a stat)
    try:
        Listing.objects.filter(pk=listing.pk).update(
            view_count=listing.view_count + 1,
        )
    except Exception:
        pass

    reviews = (
        listing.reviews
        .filter(is_published=True)
        .select_related('user')
        .order_by('-created_at')[:10]
    )
    avg_rating = (
        listing.reviews
        .filter(is_published=True)
        .aggregate(avg=Avg('rating'))['avg'] or 0
    )

    in_wishlist = False
    has_reviewed = False
    if request.user.is_authenticated:
        in_wishlist = Wishlist.objects.filter(
            user=request.user, listing=listing,
        ).exists()
        has_reviewed = listing.reviews.filter(user=request.user).exists()

    # Availability helpers
    next_available = listing.next_available_date()
    blocked_now = listing.is_blocked_now()

    today = timezone.now().date()
    active_blocks = (
        listing.availability_blocks
        .filter(status__in=['pending', 'confirmed'])
        .order_by('start_date')
    )
    current_block = active_blocks.filter(
        start_date__lte=today,
        end_date__gt=today,
    ).first()
    upcoming_blocks = active_blocks.filter(start_date__gt=today)[:5]

    # Nearby services (cross-category suggestions from the same org or area)
    nearby_services = (
        Listing.objects
        .filter(status='approved', is_active=True, accepts_bookings=True)
        .exclude(pk=listing.pk)
        .exclude(category=listing.category)
        .select_related('category', 'organization')
    )
    same_org = nearby_services.filter(organization=listing.organization)[:6]
    if same_org.count() >= 3:
        nearby_services = same_org
    else:
        loc = (listing.location or '').split(',')[0].strip()
        if loc:
            nearby_services = nearby_services.filter(location__icontains=loc)[:6]
        else:
            nearby_services = same_org[:6]

    nearby_services = _annotate_blocked_now(nearby_services)
    nearby_services = _annotate_bnb_metrics(nearby_services)

    services_by_category = {}
    for svc in nearby_services:
        services_by_category.setdefault(svc.category.slug, []).append(svc)

    # ---- B&B-specific related data (only if a bnb.Property is linked) ----
    bnb_property = None
    bnb_reviews = []
    bnb_open_maintenance_count = 0
    bnb_staff_count = 0

    try:
        bnb_property = listing.bnb_property
    except Exception:
        bnb_property = None

    if bnb_property is not None:
        try:
            bnb_reviews = list(
                bnb_property.reviews
                .order_by('-review_date')[:6]
            )
        except Exception:
            bnb_reviews = []
        try:
            bnb_open_maintenance_count = (
                bnb_property.maintenance
                .exclude(status='resolved')
                .count()
            )
        except Exception:
            bnb_open_maintenance_count = 0
        try:
            bnb_staff_count = bnb_property.staff.count()
        except Exception:
            bnb_staff_count = 0

    return render(request, 'marketplace/listing_detail.html', {
        'listing': listing,
        'reviews': reviews,
        'avg_rating': round(avg_rating, 1) if avg_rating else 0,
        'in_wishlist': in_wishlist,
        'has_reviewed': has_reviewed,
        'next_available': next_available,
        'blocked_now': blocked_now,
        'current_block': current_block,
        'upcoming_blocks': upcoming_blocks,
        'gallery_urls': listing.image_urls,
        'social_links': listing.social_links,
        'has_social_links': listing.has_social_links,
        'has_contact': listing.has_contact,
        'whatsapp_link': listing.whatsapp_link,
        'map_embed_url': listing.map_embed_url,
        'nearby_services': nearby_services,
        'services_by_category': services_by_category,

        # B&B-specific extras
        'bnb_property': bnb_property,
        'bnb_reviews': bnb_reviews,
        'bnb_open_maintenance_count': bnb_open_maintenance_count,
        'bnb_staff_count': bnb_staff_count,
    })


def book_start(request, slug):
    """
    Entry point for the guest booking flow.

    Business rules:
      • Listing must be public + accepting bookings
      • Only guests can actually book — staff are sent to their workspace
      • Occupancy is handled downstream by the overflow matcher in
        guestaccount.booking_new — the guest is NEVER blocked here.
    """
    listing = get_object_or_404(Listing, slug=slug)

    if not listing.is_public or not listing.accepts_bookings:
        messages.error(request, 'This listing is not accepting bookings.')
        return redirect('marketplace:home')

    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

    if _is_guest(request.user):
        return redirect(reverse('guestaccount:booking_new', args=[listing.slug]))

    messages.info(
        request,
        'Signed in as staff. Use your workspace to manage bookings.',
    )
    return redirect('dashboard')


@login_required
def wishlist_toggle(request, slug):
    """
    Toggle a listing in the guest's wishlist.

    Counter + org notification are handled by marketplace/signals.py
    (post_save / post_delete on Wishlist).
    """
    listing = get_object_or_404(Listing, slug=slug)

    if not _is_guest(request.user):
        messages.info(request, 'Only guest accounts can save listings.')
        return redirect('marketplace:listing_detail', slug=slug)

    item, created = Wishlist.objects.get_or_create(
        user=request.user, listing=listing,
    )
    if not created:
        item.delete()
        messages.success(request, 'Removed from your saved items.')
    else:
        messages.success(request, 'Saved to your wishlist.')

    return redirect('marketplace:listing_detail', slug=slug)


@login_required
def wishlist_list(request):
    _release_expired_blocks()

    saved_ids = (
        Wishlist.objects
        .filter(user=request.user)
        .values_list('listing_id', flat=True)
    )

    listings = (
        Listing.objects
        .filter(pk__in=saved_ids, status='approved', is_active=True)
        .select_related('category', 'organization')
        .prefetch_related('images')
        .order_by('-approved_at')
    )
    listings = _annotate_blocked_now(listings)
    listings = _annotate_bnb_metrics(listings)

    paginator = Paginator(listings, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Wrap each listing so templates that expect `item.listing` still work
    items = [SimpleNamespace(listing=l) for l in page_obj.object_list]

    return render(request, 'marketplace/wishlist.html', {
        'items': items,
        'listings': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'user_wishlist_ids': set(saved_ids),
    })


@login_required
def review_submit(request, slug):
    """
    Guest-only review submission.

    Rating aggregate + org notification are handled by
    marketplace/signals.py (post_save on Review).
    """
    listing = get_object_or_404(Listing, slug=slug)

    if not _is_guest(request.user):
        messages.info(request, 'Only guest accounts can post reviews.')
        return redirect('marketplace:listing_detail', slug=slug)

    if request.method == 'POST':
        try:
            rating = int(request.POST.get('rating') or 5)
        except (TypeError, ValueError):
            rating = 5
        rating = max(1, min(5, rating))
        title = request.POST.get('title', '').strip()
        body = request.POST.get('body', '').strip()

        Review.objects.update_or_create(
            listing=listing, user=request.user,
            defaults={
                'rating': rating,
                'title': title,
                'body': body,
                'is_published': True,
            },
        )
        messages.success(request, 'Thanks for your review!')

    return redirect(
        f"{reverse('marketplace:listing_detail', args=[slug])}#reviews"
    )


# ===========================================================================
# ORG-ADMIN MANAGEMENT VIEWS
# ===========================================================================
@login_required
def manage_home(request):
    _release_expired_blocks()

    org = _require_org_admin(request)
    if org is None and not getattr(request.user, 'is_superadmin', False):
        messages.error(request, 'You need to be an organization admin to manage listings.')
        return redirect('dashboard')

    listings = (
        Listing.objects
        .select_related('category', 'organization')
        .prefetch_related('images')
    )
    if org is not None and not getattr(request.user, 'is_superadmin', False):
        listings = listings.filter(organization=org)

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        listings = listings.filter(status=status_filter)

    category_filter = request.GET.get('category', '').strip()
    if category_filter:
        listings = listings.filter(category__slug=category_filter)

    q = request.GET.get('q', '').strip()
    if q:
        listings = listings.filter(
            Q(title__icontains=q) |
            Q(location__icontains=q) |
            Q(short_description__icontains=q)
        )

    listings = _annotate_blocked_now(listings)
    listings = _annotate_bnb_metrics(listings)
    listings = listings.order_by('-created_at')

    all_listings = Listing.objects.all()
    if org is not None and not getattr(request.user, 'is_superadmin', False):
        all_listings = all_listings.filter(organization=org)

    counts = {
        'total':       all_listings.count(),
        'approved':    all_listings.filter(status='approved').count(),
        'pending':     all_listings.filter(status='pending').count(),
        'draft':       all_listings.filter(status='draft').count(),
        'rejected':    all_listings.filter(status='rejected').count(),
        'unpublished': all_listings.filter(status='unpublished').count(),
    }

    totals = all_listings.aggregate(
        total_views=Sum('view_count'),
        total_bookings=Sum('booking_count'),
        total_reviews=Sum('review_count'),
        total_saves=Sum('wishlist_count'),
    )

    return render(request, 'marketplace/manage/home.html', {
        'listings': listings,
        'counts': counts,
        'totals': totals,
        'org': org,
        'categories': ListingCategory.objects.all(),
        'status_filter': status_filter,
        'q': q,
    })


@login_required
def manage_create(request):
    org = _require_org_admin(request)
    if org is None and not getattr(request.user, 'is_superadmin', False):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    ctx_base = {
        'mode': 'create',
        'listing': None,
        'org': org,
        'categories': ListingCategory.objects.all(),
        'max_images': MAX_GALLERY_IMAGES - 1,
        'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', ''),
    }

    if request.method == 'POST':
        form = ListingForm(request.POST, request.FILES)
        formset = ListingImageFormSet(request.POST, request.FILES)

        if form.is_valid() and formset.is_valid():
            incoming = [
                f for f in formset.forms
                if f.cleaned_data and not f.cleaned_data.get('DELETE', False)
                and (
                    f.cleaned_data.get('image')
                    or (f.cleaned_data.get('image_url') or '').strip()
                )
            ]
            if len(incoming) > MAX_GALLERY_IMAGES - 1:
                messages.error(
                    request,
                    f'Please provide at most {MAX_GALLERY_IMAGES - 1} gallery images.',
                )
                return render(request, 'marketplace/manage/form.html', {
                    'form': form, 'formset': formset, **ctx_base,
                })

            with transaction.atomic():
                listing = form.save(commit=False)
                if org is not None:
                    listing.organization = org
                listing.source_app = 'manual'
                listing.source_model = 'listing'
                listing.status = 'approved'
                listing.approved_at = timezone.now()
                listing.approved_by = request.user
                listing.is_active = True
                listing.save()

                formset.instance = listing
                formset.save()

            messages.success(
                request,
                f'"{listing.title}" is now live on the marketplace.',
            )
            return redirect('marketplace:manage_home')
    else:
        form = ListingForm()
        formset = ListingImageFormSet()

    return render(request, 'marketplace/manage/form.html', {
        'form': form, 'formset': formset, **ctx_base,
    })


@login_required
def manage_edit(request, pk):
    org = _require_org_admin(request)
    if org is None and not getattr(request.user, 'is_superadmin', False):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    listing = get_object_or_404(Listing, pk=pk)
    if not _listing_owner_or_super(request.user, listing):
        messages.error(request, 'You do not own this listing.')
        return redirect('marketplace:manage_home')

    ctx_base = {
        'mode': 'edit',
        'listing': listing,
        'org': org,
        'categories': ListingCategory.objects.all(),
        'max_images': MAX_GALLERY_IMAGES - 1,
        'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', ''),
    }

    if request.method == 'POST':
        form = ListingForm(request.POST, request.FILES, instance=listing)
        formset = ListingImageFormSet(request.POST, request.FILES, instance=listing)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                listing = form.save(commit=False)
                listing.status = 'approved'
                listing.is_active = True
                if not listing.approved_at:
                    listing.approved_at = timezone.now()
                    listing.approved_by = request.user
                listing.save()
                formset.save()

            messages.success(request, 'Listing updated — changes are live.')
            return redirect('marketplace:manage_home')
    else:
        form = ListingForm(instance=listing)
        formset = ListingImageFormSet(instance=listing)

    return render(request, 'marketplace/manage/form.html', {
        'form': form, 'formset': formset, **ctx_base,
    })


@login_required
def manage_delete(request, pk):
    org = _require_org_admin(request)
    if org is None and not getattr(request.user, 'is_superadmin', False):
        return redirect('dashboard')

    listing = get_object_or_404(Listing, pk=pk)
    if not _listing_owner_or_super(request.user, listing):
        messages.error(request, 'You do not own this listing.')
        return redirect('marketplace:manage_home')

    if request.method == 'POST':
        # Server-side type-to-confirm guard
        if request.POST.get('confirm', '').strip().lower() != 'delete':
            messages.error(request, 'Please type "delete" to confirm.')
            return redirect('marketplace:manage_delete', pk=pk)

        title = listing.title
        listing.delete()
        messages.success(request, f'Listing "{title}" deleted.')
        return redirect('marketplace:manage_home')

    return render(request, 'marketplace/manage/delete.html', {'listing': listing})


@login_required
def manage_toggle(request, pk):
    org = _require_org_admin(request)
    if org is None and not getattr(request.user, 'is_superadmin', False):
        return redirect('dashboard')

    listing = get_object_or_404(Listing, pk=pk)
    if not _listing_owner_or_super(request.user, listing):
        return redirect('marketplace:manage_home')

    if listing.status == 'approved' and listing.is_active:
        listing.status = 'unpublished'
        listing.is_active = False
        messages.success(request, 'Listing hidden from the marketplace.')
    else:
        listing.status = 'approved'
        listing.is_active = True
        if not listing.approved_at:
            listing.approved_at = timezone.now()
            listing.approved_by = request.user
        messages.success(request, 'Listing is live on the marketplace.')
    listing.save()
    return redirect('marketplace:manage_home')


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
@login_required
def manage_categories(request):
    if not (_require_org_admin(request) or getattr(request.user, 'is_superadmin', False)):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    categories = (
        ListingCategory.objects
        .all()
        .annotate(listing_total=Count('listings'))
        .order_by('display_order', 'name')
    )
    return render(request, 'marketplace/manage/categories_list.html', {
        'categories': categories,
    })


@login_required
def manage_category_create(request):
    if not (_require_org_admin(request) or getattr(request.user, 'is_superadmin', False)):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = ListingCategoryForm(request.POST)
        if form.is_valid():
            cat = form.save()
            messages.success(request, f'Category "{cat.name}" added.')
            next_url = request.GET.get('next') or request.POST.get('next') or ''
            if next_url:
                return redirect(next_url)
            return redirect('marketplace:manage_categories')
    else:
        form = ListingCategoryForm()

    return render(request, 'marketplace/manage/category_form.html', {
        'form': form,
        'mode': 'create',
        'category': None,
        'next': request.GET.get('next', ''),
    })


@login_required
def manage_category_edit(request, pk):
    if not (_require_org_admin(request) or getattr(request.user, 'is_superadmin', False)):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    category = get_object_or_404(ListingCategory, pk=pk)

    if request.method == 'POST':
        form = ListingCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category updated.')
            return redirect('marketplace:manage_categories')
    else:
        form = ListingCategoryForm(instance=category)

    return render(request, 'marketplace/manage/category_form.html', {
        'form': form,
        'mode': 'edit',
        'category': category,
        'next': '',
    })


@login_required
def manage_category_delete(request, pk):
    if not (_require_org_admin(request) or getattr(request.user, 'is_superadmin', False)):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    category = get_object_or_404(ListingCategory, pk=pk)
    listing_count = category.listings.count()

    if request.method == 'POST':
        # Server-side slug-to-confirm guard
        expected = category.slug.lower()
        provided = request.POST.get('confirm_slug', '').strip().lower()
        if provided != expected:
            messages.error(request, 'Please type the category slug to confirm deletion.')
            return redirect('marketplace:manage_category_delete', pk=pk)

        if listing_count:
            messages.error(
                request,
                f'Cannot delete "{category.name}" — it still has '
                f'{listing_count} listing(s).',
            )
            return redirect('marketplace:manage_categories')

        name = category.name
        category.delete()
        messages.success(request, f'Category "{name}" deleted.')
        return redirect('marketplace:manage_categories')

    return render(request, 'marketplace/manage/category_delete.html', {
        'category': category,
        'listing_count': listing_count,
    })


# ===========================================================================
# SUPERADMIN MODERATION
# ===========================================================================
@login_required
def moderation_queue(request):
    if not getattr(request.user, 'is_superadmin', False):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    pending = (
        Listing.objects
        .filter(status='pending')
        .select_related('category', 'organization')
        .prefetch_related('images')
        .order_by('-created_at')
    )
    pending = _annotate_blocked_now(pending)
    pending = _annotate_bnb_metrics(pending)

    counts = Listing.objects.aggregate(
        pending=Count('id', filter=Q(status='pending')),
        approved=Count('id', filter=Q(status='approved')),
        rejected=Count('id', filter=Q(status='rejected')),
    )

    return render(request, 'marketplace/manage/moderation_queue.html', {
        'pending': pending,
        'counts': counts,
    })


@login_required
def moderation_approve(request, pk):
    if not getattr(request.user, 'is_superadmin', False):
        return redirect('dashboard')
    listing = get_object_or_404(Listing, pk=pk)
    approve(listing, by_user=request.user)
    messages.success(request, f'"{listing.title}" approved.')
    return redirect('marketplace:moderation_queue')


@login_required
def moderation_reject(request, pk):
    if not getattr(request.user, 'is_superadmin', False):
        return redirect('dashboard')
    listing = get_object_or_404(Listing, pk=pk)
    note = request.POST.get('note', '').strip()
    reject(listing, note=note, by_user=request.user)
    messages.success(request, f'"{listing.title}" rejected.')
    return redirect('marketplace:moderation_queue')