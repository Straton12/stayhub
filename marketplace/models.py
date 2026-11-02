# marketplace/models.py
from math import radians, sin, cos, asin, sqrt

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

EARTH_RADIUS_KM = 6371.0

# Max gallery images per listing (cover image is separate, stored on Listing)
MAX_GALLERY_IMAGES = 4


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------
class ListingCategory(models.Model):
    SLUG_CHOICES = [
        ('stays',     'Stays'),
        ('tours',     'Tours & Travel'),
        ('food',      'Restaurants & Food'),
        ('laundry',   'Laundry'),
        ('transport', 'Transport'),
    ]
    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    icon = models.CharField(max_length=40, default='grid')
    accent = models.CharField(max_length=20, default='indigo')
    display_order = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'Listing categories'

    def __str__(self):
        return self.name

    @property
    def listing_count(self):
        return self.listings.count()


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
class Listing(models.Model):
    STATUS_CHOICES = [
        ('draft',       'Draft'),
        ('pending',     'Pending review'),
        ('approved',    'Approved'),
        ('rejected',    'Rejected'),
        ('unpublished', 'Unpublished'),
    ]
    CANCELLATION_CHOICES = [
        ('flexible',  'Flexible'),
        ('moderate',  'Moderate'),
        ('strict',    'Strict'),
        ('nonrefund', 'Non-refundable'),
    ]
    PAYMENT_POLICY = [
        ('pay_now',           'Pay now (online)'),
        ('pay_on_arrival',    'Pay on arrival'),
        ('pay_on_delivery',   'Pay on delivery'),
        ('pay_on_completion', 'Pay on completion'),
        ('pay_deposit',       'Pay deposit now, rest later'),
    ]

    # Ownership / routing
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='marketplace_listings',
    )
    category = models.ForeignKey(
        ListingCategory, on_delete=models.PROTECT,
        related_name='listings',
    )
    source_app = models.CharField(max_length=40, blank=True)
    source_model = models.CharField(max_length=40, blank=True)
    source_id = models.PositiveIntegerField(null=True, blank=True)

    # Public copy
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    short_description = models.CharField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    cover_image_url = models.URLField(blank=True)
    cover_image = models.ImageField(
        upload_to='marketplace/covers/', blank=True, null=True,
    )

    # Location
    location = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=300, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Contact (all optional)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_email = models.EmailField(blank=True)
    whatsapp = models.CharField(
        max_length=30, blank=True,
        help_text='Include country code, e.g. +254712345678',
    )

    # Social media links (all optional — only filled ones render)
    website = models.URLField(blank=True)
    facebook = models.URLField(blank=True)
    instagram = models.URLField(blank=True)
    twitter = models.URLField(blank=True)
    tiktok = models.URLField(blank=True)
    youtube = models.URLField(blank=True)

    # Commercial
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price_unit = models.CharField(max_length=40, default='per night')
    min_nights = models.PositiveIntegerField(default=1)
    max_guests = models.PositiveIntegerField(default=2)
    bedrooms = models.PositiveIntegerField(default=1)
    beds = models.PositiveIntegerField(default=1)
    baths = models.PositiveIntegerField(default=1)

    # Payment + fees
    payment_policy = models.CharField(
        max_length=30, choices=PAYMENT_POLICY, default='pay_now',
    )
    deposit_percent = models.PositiveIntegerField(
        default=0, help_text='If payment_policy=pay_deposit, % due now.',
    )
    service_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=5,
        help_text='Marketplace service fee added at checkout.',
    )

    # Amenities / rules
    amenities = models.TextField(blank=True, help_text='One per line')
    house_rules = models.TextField(blank=True, help_text='One per line')
    check_in_time = models.CharField(max_length=40, blank=True, default='14:00')
    check_out_time = models.CharField(max_length=40, blank=True, default='10:00')
    cancellation_policy = models.CharField(
        max_length=20, choices=CANCELLATION_CHOICES, default='moderate',
    )

    # Moderation
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_active = models.BooleanField(default=True)
    accepts_bookings = models.BooleanField(default=True)
    pay_first = models.BooleanField(default=True)
    rejection_note = models.TextField(blank=True)

    # Stats
    view_count = models.PositiveIntegerField(default=0)
    booking_count = models.PositiveIntegerField(default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    review_count = models.PositiveIntegerField(default=0)
    wishlist_count = models.PositiveIntegerField(
        default=0, help_text='Denormalised count of saves/likes.',
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='marketplace_approvals',
    )

    class Meta:
        ordering = ['-approved_at', '-created_at']
        indexes = [
            models.Index(fields=['status', 'is_active']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['source_app', 'source_model', 'source_id']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.title}-{self.organization_id}") or 'listing'
            s, n = base, 2
            while Listing.objects.filter(slug=s).exclude(pk=self.pk).exists():
                s = f"{base}-{n}"
                n += 1
            self.slug = s
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.latitude is not None and not (-90 <= float(self.latitude) <= 90):
            raise ValidationError({'latitude': 'Latitude must be between -90 and 90.'})
        if self.longitude is not None and not (-180 <= float(self.longitude) <= 180):
            raise ValidationError({'longitude': 'Longitude must be between -180 and 180.'})

    # -- Convenience ---------------------------------------------------------
    @property
    def is_public(self):
        return self.status == 'approved' and self.is_active

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def amenities_list(self):
        return [a.strip() for a in (self.amenities or '').splitlines() if a.strip()]

    @property
    def house_rules_list(self):
        return [r.strip() for r in (self.house_rules or '').splitlines() if r.strip()]

    @property
    def social_links(self):
        """
        Return a list of dicts for only the social links that are filled in.
        Template usage:
            {% for s in listing.social_links %}
                <a href="{{ s.url }}" class="social-{{ s.key }}">{{ s.label }}</a>
            {% endfor %}
        """
        entries = [
            ('website',   'Website',   self.website),
            ('facebook',  'Facebook',  self.facebook),
            ('instagram', 'Instagram', self.instagram),
            ('twitter',   'X / Twitter', self.twitter),
            ('tiktok',    'TikTok',    self.tiktok),
            ('youtube',   'YouTube',   self.youtube),
        ]
        return [
            {'key': key, 'label': label, 'url': url.strip()}
            for key, label, url in entries
            if url and url.strip()
        ]

    @property
    def has_social_links(self):
        return bool(self.social_links)

    @property
    def has_contact(self):
        return bool(self.contact_phone or self.contact_email or self.whatsapp)

    @property
    def whatsapp_link(self):
        if not self.whatsapp:
            return ''
        digits = ''.join(ch for ch in self.whatsapp if ch.isdigit())
        return f"https://wa.me/{digits}" if digits else ''

    @property
    def map_embed_url(self):
        """
        Return a Google Maps embed URL using the coordinates (no API key needed
        for the basic 'place' embed). Falls back to a search by address.
        """
        if self.has_location:
            return (
                f"https://www.google.com/maps?q="
                f"{self.latitude},{self.longitude}&z=15&output=embed"
            )
        if self.address or self.location:
            from urllib.parse import quote_plus
            q = quote_plus(self.address or self.location)
            return f"https://www.google.com/maps?q={q}&z=15&output=embed"
        return ''

    @property
    def image_urls(self):
        """
        Return up to MAX_GALLERY_IMAGES public image URLs, cover first.
        """
        urls = []
        # Cover first
        if self.cover_image:
            urls.append(self.cover_image.url)
        elif self.cover_image_url:
            urls.append(self.cover_image_url)
        # Then gallery
        for img in self.images.all():
            if len(urls) >= MAX_GALLERY_IMAGES:
                break
            if img.image:
                urls.append(img.image.url)
            elif img.image_url:
                urls.append(img.image_url)
        return urls[:MAX_GALLERY_IMAGES]

    @property
    def source_row(self):
        """Return the underlying product row, or None."""
        if not (self.source_app and self.source_model and self.source_id):
            return None
        try:
            from django.apps import apps
            model = apps.get_model(self.source_app, self.source_model)
            return model.objects.filter(pk=self.source_id).first()
        except Exception:
            return None

    def distance_from(self, lat, lng):
        if not self.has_location:
            return None
        return haversine_km(
            float(lat), float(lng),
            float(self.latitude), float(self.longitude),
        )

    # -- Availability --------------------------------------------------------
    def is_available(self, start, end, exclude_booking_id=None):
        """
        True if no confirmed/pending block overlaps [start, end).
        """
        qs = self.availability_blocks.filter(status__in=['confirmed', 'pending'])
        if exclude_booking_id:
            qs = qs.exclude(guest_booking_id=exclude_booking_id)
        for blk in qs:
            if blk.start_date < end and blk.end_date > start:
                return False
        return True

    def next_available_date(self, from_date=None):
        from datetime import timedelta
        d = from_date or timezone.now().date()
        for _ in range(365):
            block = self.availability_blocks.filter(
                status__in=['confirmed', 'pending'],
                start_date__lte=d, end_date__gt=d,
            ).first()
            if not block:
                return d
            d = block.end_date
        return None

    def is_blocked_now(self):
        today = timezone.now().date()
        return self.availability_blocks.filter(
            status__in=['confirmed', 'pending'],
            start_date__lte=today, end_date__gt=today,
        ).exists()

    def release_expired_blocks(self):
        """
        Mark all confirmed/pending blocks whose end_date has passed as 'released'
        so the listing is instantly bookable again.
        Returns the number of blocks released.
        """
        today = timezone.now().date()
        return self.availability_blocks.filter(
            status__in=['confirmed', 'pending'],
            end_date__lte=today,
        ).update(status='released')

    def recalc_rating(self):
        from django.db.models import Avg
        published = self.reviews.filter(is_published=True)
        agg = published.aggregate(avg=Avg('rating'))
        self.average_rating = round(agg['avg'] or 0, 2)
        self.review_count = published.count()
        self.save(update_fields=['average_rating', 'review_count', 'updated_at'])

    def recalc_wishlist_count(self):
        self.wishlist_count = self.wishlisted_by.count()
        self.save(update_fields=['wishlist_count', 'updated_at'])


# ---------------------------------------------------------------------------
# Availability block
# ---------------------------------------------------------------------------
class ListingAvailabilityBlock(models.Model):
    STATUS = [
        ('pending',   'Pending'),
        ('confirmed', 'Confirmed'),
        ('released',  'Released'),
    ]
    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE,
        related_name='availability_blocks',
    )
    guest_booking = models.ForeignKey(
        'guestaccount.GuestBooking', on_delete=models.CASCADE,
        null=True, blank=True, related_name='availability_blocks',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_date']
        indexes = [models.Index(fields=['listing', 'start_date', 'end_date'])]

    def __str__(self):
        return f"{self.listing} · {self.start_date}→{self.end_date} ({self.status})"

    @property
    def is_expired(self):
        return self.end_date < timezone.now().date()

    @property
    def is_active_block(self):
        return self.status in ('pending', 'confirmed')


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------
class ListingImage(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='marketplace/gallery/', blank=True, null=True)
    image_url = models.URLField(blank=True)
    caption = models.CharField(max_length=200, blank=True)
    display_order = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.caption or f"Image #{self.pk} for {self.listing_id}"

    def clean(self):
        super().clean()
        if not self.image and not (self.image_url or '').strip():
            raise ValidationError('Provide an image file or an image URL.')
        # Enforce the per-listing cap
        if self.listing_id:
            siblings = ListingImage.objects.filter(listing_id=self.listing_id)
            if self.pk:
                siblings = siblings.exclude(pk=self.pk)
            if siblings.count() >= MAX_GALLERY_IMAGES:
                raise ValidationError(
                    f'Only {MAX_GALLERY_IMAGES} gallery images are allowed per listing.'
                )





# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
class Review(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='marketplace_reviews',
    )
    rating = models.PositiveSmallIntegerField(default=5)
    title = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('listing', 'user')

    def __str__(self):
        return f"{self.user} → {self.listing} ({self.rating}★)"

    def clean(self):
        super().clean()
        if not (1 <= self.rating <= 5):
            raise ValidationError({'rating': 'Rating must be between 1 and 5.'})
    # NOTE: save()/delete() side-effects live in marketplace/signals.py

    
# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
class Wishlist(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='wishlist_items',
    )
    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE,
        related_name='wishlisted_by',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'listing')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} ♥ {self.listing}"

    # NOTE: side-effects (wishlist_count update + org notification)
    # live in marketplace/signals.py — do NOT add save()/delete() here.
    

# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------
def haversine_km(lat1, lng1, lat2, lng2):
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))