# bnb/models.py
import builtins
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# ============================================================
#  CONSTANTS
# ============================================================

# The canonical definition of "a booking that counts as revenue".
# Used by Property.total_revenue, Booking.is_revenue, and any
# report or aggregate that needs to sum booking revenue.
REVENUE_STATUSES = ('confirmed', 'checked_in', 'checked_out')

# Bookings that still owe money AND whose balance should be
# included in "outstanding" totals.
OUTSTANDING_STATUSES = ('pending', 'confirmed', 'checked_in')

# Invoice statuses that still have a balance to collect.
INVOICE_OPEN_STATUSES = ('draft', 'sent', 'overdue')


# ============================================================
#  PROPERTY  (single bookable thing — replaces Property + Unit)
# ============================================================
class Property(models.Model):
    """
    One Property = one bookable thing that appears on the marketplace.

    No more Unit model. Everything lives on the Property:
      • images (max 4: cover + 3 extras)
      • contact (phone, email, WhatsApp)
      • socials (all optional)
      • location (lat/lng + address + label)
      • price / capacity / rules
    """

    # ---------- Identity ----------
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_properties',
    )
    name = models.CharField(max_length=200)

    # Category links to the marketplace taxonomy (stays/tours/food/...)
    category = models.ForeignKey(
        'marketplace.ListingCategory', on_delete=models.PROTECT,
        related_name='bnb_properties',
        help_text='Where this property appears on the marketplace.',
    )

    description = models.TextField(blank=True)
    short_description = models.CharField(max_length=280, blank=True)

    # ---------- Location ----------
    location_label = models.CharField(
        max_length=200, blank=True,
        help_text='e.g. Westlands, Nairobi — shown on cards.',
    )
    address = models.CharField(max_length=300, blank=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
    )

    # ---------- Contact ----------
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    whatsapp = models.CharField(
        max_length=30, blank=True,
        help_text='Include country code, e.g. +254712345678.',
    )

    # ---------- Social links (all optional) ----------
    website = models.URLField(blank=True)
    facebook = models.URLField(blank=True)
    instagram = models.URLField(blank=True)
    twitter = models.URLField(blank=True)
    tiktok = models.URLField(blank=True)
    youtube = models.URLField(blank=True)

    # ---------- Commercial ----------
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price_unit = models.CharField(
        max_length=40, default='per night',
        help_text='e.g. per night, per person, per item.',
    )
    min_nights = models.PositiveIntegerField(default=1)
    max_guests = models.PositiveIntegerField(default=2)
    bedrooms = models.PositiveIntegerField(default=1)
    baths = models.PositiveIntegerField(default=1)

    # ---------- Check-in / out times ----------
    check_in_time = models.CharField(max_length=40, blank=True, default='14:00')
    check_out_time = models.CharField(max_length=40, blank=True, default='10:00')

    # ---------- Amenities / rules (one per line) ----------
    amenities = models.TextField(blank=True, help_text='One per line.')
    house_rules = models.TextField(blank=True, help_text='One per line.')

    # ---------- Images (max 4 — cover required in form) ----------
    cover_image = models.ImageField(
        upload_to='bnb/covers/', null=True, blank=True,
        help_text='Required. The primary image shown on cards.',
    )
    image_2 = models.ImageField(upload_to='bnb/covers/', null=True, blank=True)
    image_3 = models.ImageField(upload_to='bnb/covers/', null=True, blank=True)
    image_4 = models.ImageField(upload_to='bnb/covers/', null=True, blank=True)

    # ---------- Link to the marketplace listing ----------
    listing = models.OneToOneField(
        'marketplace.Listing', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bnb_property',
    )

    # ---------- Status ----------
    is_active = models.BooleanField(default=True)

    # ---------- Timestamps ----------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Properties'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return self.name

    # ---------------------------------------------------------------
    #  Convenience properties
    # ---------------------------------------------------------------
    @builtins.property
    def images(self):
        """Return the list of image fields that are actually set."""
        return [
            img for img in
            (self.cover_image, self.image_2, self.image_3, self.image_4)
            if img
        ]

    @builtins.property
    def image_urls(self):
        """Public URLs for all uploaded images, in order."""
        return [img.url for img in self.images]

    @builtins.property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    @builtins.property
    def amenities_list(self):
        return [a.strip() for a in (self.amenities or '').splitlines() if a.strip()]

    @builtins.property
    def house_rules_list(self):
        return [r.strip() for r in (self.house_rules or '').splitlines() if r.strip()]

    @builtins.property
    def social_links(self):
        """
        Return a list of only the social links that are filled in.
        Each entry: {'key': ..., 'label': ..., 'url': ...}
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
            {'key': k, 'label': l, 'url': (u or '').strip()}
            for k, l, u in entries
            if u and u.strip()
        ]

    @builtins.property
    def has_social_links(self):
        return bool(self.social_links)

    @builtins.property
    def has_contact(self):
        return bool(self.phone or self.email or self.whatsapp)

    @builtins.property
    def whatsapp_link(self):
        if not self.whatsapp:
            return ''
        digits = ''.join(ch for ch in self.whatsapp if ch.isdigit())
        return f"https://wa.me/{digits}" if digits else ''

    @builtins.property
    def map_embed_url(self):
        """
        Google Maps embed URL (no API key needed for the basic place embed).
        """
        if self.has_location:
            return (
                f"https://www.google.com/maps?q="
                f"{self.latitude},{self.longitude}&z=15&output=embed"
            )
        if self.address or self.location_label:
            from urllib.parse import quote_plus
            q = quote_plus(self.address or self.location_label)
            return f"https://www.google.com/maps?q={q}&z=15&output=embed"
        return ''

    # ---------------------------------------------------------------
    #  Booking statistics
    # ---------------------------------------------------------------
    @builtins.property
    def total_bookings(self):
        return self.bookings.count()

    @builtins.property
    def total_revenue(self):
        agg = self.bookings.filter(
            status__in=REVENUE_STATUSES,
        ).aggregate(total=models.Sum('total_amount'))
        return agg['total'] or Decimal('0.00')

    @builtins.property
    def upcoming_bookings_count(self):
        today = timezone.now().date()
        return self.bookings.filter(
            check_in__gte=today,
        ).exclude(status__in=['cancelled', 'checked_out']).count()

    @builtins.property
    def active_bookings_count(self):
        return self.bookings.filter(status='checked_in').count()

    @builtins.property
    def is_currently_booked(self):
        """
        True if there's a confirmed or in-house booking whose date range
        includes today. Used to grey out the marketplace listing.
        """
        today = timezone.now().date()
        return self.bookings.filter(
            status__in=['confirmed', 'checked_in'],
            check_in__lte=today,
            check_out__gte=today,
        ).exists()

    @builtins.property
    def next_available_date(self):
        """First date from today with no active booking block."""
        today = timezone.now().date()
        next_block = (
            self.bookings
            .filter(
                status__in=['confirmed', 'checked_in'],
                check_out__gte=today,
            )
            .order_by('check_out')
            .first()
        )
        return next_block.check_out if next_block else today

    # ---------------------------------------------------------------
    #  Validation
    # ---------------------------------------------------------------
    def clean(self):
        super().clean()
        if self.latitude is not None and not (-90 <= float(self.latitude) <= 90):
            raise ValidationError({'latitude': 'Latitude must be between -90 and 90.'})
        if self.longitude is not None and not (-180 <= float(self.longitude) <= 180):
            raise ValidationError({'longitude': 'Longitude must be between -180 and 180.'})


# ============================================================
#  GUESTS
# ============================================================
class Guest(models.Model):
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_guests', null=True, blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bnb_guest_profiles',
        help_text='Link to the marketplace guest account, if any.',
    )
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    country = models.CharField(max_length=100, blank=True)
    id_number = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)

    total_stays = models.PositiveIntegerField(default=0)
    total_spent = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    is_blacklisted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return self.full_name

    # ---------------------------------------------------------------
    #  Helpers
    # ---------------------------------------------------------------
    @builtins.property
    def booking_count(self):
        return self.bookings.count()

    @builtins.property
    def last_stay(self):
        return (
            self.bookings
            .filter(status='checked_out')
            .order_by('-check_out')
            .first()
        )

    @builtins.property
    def is_returning(self):
        return self.booking_count > 1


# ============================================================
#  BOOKINGS
# ============================================================
class Booking(models.Model):
    STATUS = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ]
    SOURCE = [
        ('direct', 'Direct'),
        ('airbnb', 'Airbnb'),
        ('booking', 'Booking.com'),
        ('expedia', 'Expedia'),
        ('agent', 'Travel Agent'),
        ('referral', 'Referral'),
        ('marketplace', 'Marketplace'),
        ('walk_in', 'Walk In'),
    ]
    PAYMENT_STATUS = [
        ('unpaid', 'Unpaid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
    ]

    # Was FK to Unit — now FK to Property directly
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE,
        related_name='bookings',
    )
    guest = models.ForeignKey(
        Guest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bookings',
    )
    guest_booking = models.OneToOneField(
        'guestaccount.GuestBooking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bnb_booking',
    )

    guest_name = models.CharField(max_length=200)
    guest_email = models.EmailField(blank=True)
    guest_phone = models.CharField(max_length=30, blank=True)

    check_in = models.DateField()
    check_out = models.DateField()
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    source = models.CharField(max_length=20, choices=SOURCE, default='direct')
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default='unpaid',
    )

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cleaning_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    notes = models.TextField(blank=True)
    special_requests = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['property', 'check_in', 'check_out']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.guest_name} @ {self.property.name} ({self.check_in})"

    # ---------------------------------------------------------------
    #  Money helpers
    # ---------------------------------------------------------------
    @builtins.property
    def balance(self):
        return self.total_amount - self.amount_paid

    @builtins.property
    def amount_due(self):
        """Alias for balance — balance is what's still owed."""
        return self.balance

    @builtins.property
    def is_paid(self):
        return self.amount_paid >= self.total_amount

    @builtins.property
    def is_revenue(self):
        """True when this booking counts toward revenue totals."""
        return self.status in REVENUE_STATUSES

    @builtins.property
    def is_outstanding(self):
        """True when a balance is still owed."""
        return self.balance > 0 and self.status in OUTSTANDING_STATUSES

    @builtins.property
    def outstanding_amount(self):
        """Balance owed, clamped at zero."""
        b = self.balance
        return b if b > 0 else Decimal('0.00')

    # ---------------------------------------------------------------
    #  Date helpers
    # ---------------------------------------------------------------
    @builtins.property
    def nights(self):
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return 0

    @builtins.property
    def nights_remaining(self):
        """Days until check-out. Negative once past check-out."""
        if self.check_out:
            return (self.check_out - timezone.now().date()).days
        return 0

    @builtins.property
    def is_upcoming(self):
        return self.check_in > timezone.now().date()

    @builtins.property
    def is_active(self):
        """Guest is currently in-house."""
        return self.status == 'checked_in'

    def save(self, *args, **kwargs):
        # Keep payment_status in sync with amounts
        if not self.amount_paid or self.amount_paid <= 0:
            self.payment_status = 'unpaid'
        elif self.total_amount and self.amount_paid < self.total_amount:
            self.payment_status = 'partial'
        else:
            self.payment_status = 'paid'
        super().save(*args, **kwargs)


# ============================================================
#  HOUSEKEEPING & MAINTENANCE
# ============================================================
class HousekeepingTask(models.Model):
    STATUS = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
    ]
    PRIORITY = [
        ('low', 'Low'), ('normal', 'Normal'),
        ('high', 'High'), ('urgent', 'Urgent'),
    ]
    TASK_TYPE = [
        ('cleaning', 'Cleaning'),
        ('laundry', 'Laundry'),
        ('inspection', 'Inspection'),
        ('restock', 'Restock Supplies'),
        ('other', 'Other'),
    ]

    # Was FK to Unit — now FK to Property
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE,
        related_name='tasks',
    )
    task_type = models.CharField(max_length=20, choices=TASK_TYPE, default='cleaning')
    description = models.CharField(max_length=255)
    assigned_to = models.CharField(max_length=120, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY, default='normal')
    status = models.CharField(max_length=20, choices=STATUS, default='open')

    scheduled_for = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_task_type_display()} - {self.property.name}"

    # ---------------------------------------------------------------
    #  Helpers
    # ---------------------------------------------------------------
    @builtins.property
    def is_open(self):
        return self.status == 'open'

    @builtins.property
    def is_done(self):
        return self.status == 'done'

    @builtins.property
    def is_overdue(self):
        if self.is_done or not self.scheduled_for:
            return False
        return self.scheduled_for < timezone.now()

    @builtins.property
    def duration_label(self):
        if not self.scheduled_for or not self.completed_at:
            return '—'
        delta = self.completed_at - self.scheduled_for
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(hours * 60)}m"
        if hours < 24:
            return f"{int(hours)}h"
        return f"{int(hours // 24)}d"


class MaintenanceRequest(models.Model):
    STATUS = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
    ]
    PRIORITY = [
        ('low', 'Low'), ('normal', 'Normal'),
        ('high', 'High'), ('urgent', 'Urgent'),
    ]
    CATEGORY = [
        ('plumbing', 'Plumbing'),
        ('electrical', 'Electrical'),
        ('hvac', 'HVAC / AC'),
        ('furniture', 'Furniture'),
        ('appliance', 'Appliance'),
        ('structural', 'Structural'),
        ('other', 'Other'),
    ]

    # Was FK to Unit — now FK to Property
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE,
        related_name='maintenance',
    )
    category = models.CharField(max_length=20, choices=CATEGORY, default='other')
    issue = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    reported_by = models.CharField(max_length=120, blank=True)
    assigned_to = models.CharField(max_length=120, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY, default='normal')
    status = models.CharField(max_length=20, choices=STATUS, default='open')
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.issue} - {self.property.name}"

    # ---------------------------------------------------------------
    #  Helpers
    # ---------------------------------------------------------------
    @builtins.property
    def is_open(self):
        return self.status == 'open'

    @builtins.property
    def is_resolved(self):
        return self.status == 'resolved'

    @builtins.property
    def resolution_days(self):
        if not self.resolved_at:
            return None
        return (self.resolved_at - self.created_at).days

    @builtins.property
    def duration_label(self):
        if self.resolved_at:
            days = self.resolution_days
            if days == 0:
                hours = (self.resolved_at - self.created_at).total_seconds() / 3600
                return f"{int(hours)}h"
            return f"{days}d"
        return '—'


# ============================================================
#  FINANCE
# ============================================================
class ExpenseCategory(models.Model):
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='expense_categories', null=True, blank=True,
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_recurring = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Expense Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Expense(models.Model):
    FREQUENCY = [
        ('one_off', 'One-off'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ]
    PAYMENT_METHOD = [
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
        ('card', 'Card'),
        ('mobile', 'Mobile Money'),
        ('cheque', 'Cheque'),
        ('other', 'Other'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='expenses', null=True, blank=True,
    )
    property = models.ForeignKey(
        Property, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expenses',
    )
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expenses',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    frequency = models.CharField(max_length=20, choices=FREQUENCY, default='one_off')
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD, default='cash',
    )
    vendor = models.CharField(max_length=200, blank=True)
    expense_date = models.DateField(default=timezone.now)
    paid = models.BooleanField(default=True)
    receipt = models.FileField(upload_to='bnb/expenses/', blank=True, null=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bnb_expenses_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-expense_date', '-created_at']

    def __str__(self):
        return f"{self.title} - {self.amount}"

    # ---------------------------------------------------------------
    #  Helpers
    # ---------------------------------------------------------------
    @builtins.property
    def is_recurring(self):
        return self.frequency != 'one_off'

    @builtins.property
    def category_label(self):
        return self.category.name if self.category_id else 'Uncategorised'

    @builtins.property
    def frequency_label(self):
        return self.get_frequency_display()

    @builtins.property
    def payment_method_label(self):
        return self.get_payment_method_display()


class Revenue(models.Model):
    SOURCE = [
        ('booking', 'Booking'),
        ('late_checkout', 'Late Checkout'),
        ('minibar', 'Minibar'),
        ('event', 'Event'),
        ('cleaning', 'Cleaning Fee'),
        ('other', 'Other'),
    ]
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_revenues', null=True, blank=True,
    )
    property = models.ForeignKey(
        Property, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='revenues',
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='extra_revenues',
    )
    title = models.CharField(max_length=200)
    source = models.CharField(max_length=20, choices=SOURCE, default='other')
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    revenue_date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-revenue_date']

    def __str__(self):
        return f"{self.title} - {self.amount}"

    # ---------------------------------------------------------------
    #  Helpers
    # ---------------------------------------------------------------
    @builtins.property
    def source_label(self):
        return self.get_source_display()

    @builtins.property
    def is_booking_revenue(self):
        return self.source == 'booking'

    @builtins.property
    def amount_signed(self):
        """Always positive — helper for template display."""
        return self.amount


class Invoice(models.Model):
    STATUS = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('void', 'Void'),
    ]
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_invoices', null=True, blank=True,
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoices',
    )
    invoice_number = models.CharField(max_length=50, unique=True)
    guest_name = models.CharField(max_length=200)
    guest_email = models.EmailField(blank=True)
    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS, default='draft')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issue_date']

    def __str__(self):
        return self.invoice_number

    # ---------------------------------------------------------------
    #  Helpers
    # ---------------------------------------------------------------
    @builtins.property
    def balance(self):
        return self.total - self.amount_paid

    @builtins.property
    def is_outstanding(self):
        return self.balance > 0 and self.status in INVOICE_OPEN_STATUSES

    @builtins.property
    def is_settled(self):
        return self.status == 'paid' and self.balance <= 0

    @builtins.property
    def is_overdue(self):
        if self.status == 'overdue':
            return True
        if self.due_date and self.balance > 0:
            return self.due_date < timezone.now().date()
        return False

    @builtins.property
    def days_overdue(self):
        if not self.is_overdue or not self.due_date:
            return 0
        return (timezone.now().date() - self.due_date).days

    @builtins.property
    def status_color(self):
        """CSS-friendly status key: green / amber / red / gray."""
        if self.status == 'paid':
            return 'green'
        if self.is_overdue:
            return 'red'
        if self.status in ('draft', 'sent'):
            return 'amber'
        return 'gray'


class Payment(models.Model):
    METHOD = [
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
        ('card', 'Card'),
        ('mobile', 'Mobile Money'),
        ('other', 'Other'),
    ]
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_payments', null=True, blank=True,
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments',
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    method = models.CharField(max_length=20, choices=METHOD, default='cash')
    reference = models.CharField(max_length=120, blank=True)
    payment_date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date']

    def __str__(self):
        return f"Payment {self.amount} - {self.payment_date}"

    # ---------------------------------------------------------------
    #  Helpers
    # ---------------------------------------------------------------
    @builtins.property
    def method_label(self):
        return self.get_method_display()

    @builtins.property
    def is_income(self):
        return self.amount > 0


# ============================================================
#  STAFF / REVIEWS / LOGS
# ============================================================
class StaffMember(models.Model):
    ROLE = [
        ('manager', 'Manager'),
        ('receptionist', 'Receptionist'),
        ('housekeeper', 'Housekeeper'),
        ('maintenance', 'Maintenance'),
        ('accountant', 'Accountant'),
        ('security', 'Security'),
        ('other', 'Other'),
    ]
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_staff', null=True, blank=True,
    )
    property = models.ForeignKey(
        Property, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='staff',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bnb_staff_profiles',
    )
    full_name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=20, choices=ROLE, default='other')
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hire_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})"

    # ---------------------------------------------------------------
    #  Helpers
    # ---------------------------------------------------------------
    @builtins.property
    def is_manager(self):
        return self.role == 'manager'

    @builtins.property
    def is_assigned(self):
        return self.property_id is not None

    @builtins.property
    def years_of_service(self):
        if not self.hire_date:
            return 0
        delta = timezone.now().date() - self.hire_date
        return max(0, delta.days // 365)


class Review(models.Model):
    SOURCE = [
        ('airbnb', 'Airbnb'),
        ('booking', 'Booking.com'),
        ('google', 'Google'),
        ('direct', 'Direct'),
        ('other', 'Other'),
    ]
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_reviews', null=True, blank=True,
    )
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE,
        related_name='reviews',
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviews',
    )
    guest_name = models.CharField(max_length=200)
    rating = models.PositiveSmallIntegerField(default=5)
    comment = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=SOURCE, default='direct')
    review_date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-review_date']

    def __str__(self):
        return f"{self.guest_name} - {self.rating}★"


class ActivityLog(models.Model):
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_activities', null=True, blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    action = models.CharField(max_length=200)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Activity Logs'

    def __str__(self):
        return f"{self.action} @ {self.created_at}"


# ============================================================
#  AMENITY
# ============================================================
class Amenity(models.Model):
    """
    A reusable amenity belonging to one organization.

    Orgs build a library of amenities (e.g. WiFi, Air conditioning)
    and then pick from it when creating/editing a Property. Kept
    per-organization so different orgs can curate their own lists.
    """
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_amenities',
    )
    name = models.CharField(max_length=80)
    icon = models.CharField(
        max_length=40, default='check',
        help_text='Short icon key (wifi, pool, parking, kitchen, tv, …).',
    )
    category = models.CharField(
        max_length=40, default='general',
        help_text='Grouping label (general, safety, comfort, outdoor, …).',
    )
    display_order = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'Amenities'
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'name'],
                name='unique_amenity_per_org',
            ),
        ]

    def __str__(self):
        return self.name

    @builtins.property
    def label_lower(self):
        return self.name.lower()


# ============================================================
#  PRICING RULE
# ============================================================
class PricingRule(models.Model):
    """
    A pricing rule belonging to one organization.

    Rules can be:
      • informational  (a note like "Cleaning fee applies")
      • numerical      (base price multiplier, min/max nights, fee %)

    Each rule can optionally be scoped to a single property; when
    property is null it applies to the whole organization.
    """
    RULE_TYPE_CHOICES = [
        ('base',         'Base price'),
        ('min_nights',   'Minimum nights'),
        ('max_nights',   'Maximum nights'),
        ('weekly',       'Weekly discount'),
        ('monthly',      'Monthly discount'),
        ('last_minute',  'Last-minute discount'),
        ('early_bird',   'Early-bird discount'),
        ('cleaning_fee', 'Cleaning fee'),
        ('tax',          'Tax / VAT'),
        ('extra_guest',  'Extra guest fee'),
        ('pet_fee',      'Pet fee'),
        ('other',        'Other'),
    ]
    VALUE_TYPE_CHOICES = [
        ('note',       'Note (text only)'),
        ('amount',     'Fixed amount (KES)'),
        ('percent',    'Percentage (%)'),
        ('multiplier', 'Multiplier (e.g. 1.5×)'),
        ('number',     'Number (nights, guests, …)'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_pricing_rules',
    )
    # Optional — when set, the rule applies only to this property
    applies_to_property = models.ForeignKey(
        'bnb.Property', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='pricing_rules',
    )

    rule_type = models.CharField(
        max_length=20, choices=RULE_TYPE_CHOICES, default='base',
    )
    value_type = models.CharField(
        max_length=20, choices=VALUE_TYPE_CHOICES, default='note',
    )
    label = models.CharField(
        max_length=120,
        help_text='Short name shown in the rules list.',
    )
    description = models.TextField(
        blank=True,
        help_text='Explain what this rule does (shown under the label).',
    )
    value = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Numeric value (ignored when value_type is "note").',
    )

    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=10)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'label']
        verbose_name_plural = 'Pricing rules'

    def __str__(self):
        scope = self.applies_to_property.name if self.applies_to_property_id else 'All properties'
        return f"{self.label} ({scope})"

    @builtins.property
    def value_display(self):
        """Return a human-readable value string."""
        if self.value_type == 'note':
            return '—'
        if self.value_type == 'amount':
            return f"KES {self.value:,.0f}"
        if self.value_type == 'percent':
            return f"{self.value:g}%"
        if self.value_type == 'multiplier':
            return f"{self.value:g}×"
        if self.value_type == 'number':
            return f"{self.value:g}"
        return str(self.value)
    
    
    
# bnb/models.py — append at the bottom

# ============================================================
#  LEDGER  — every money movement, timestamped & classified
# ============================================================
class LedgerEntry(models.Model):
    """
    Immutable audit trail of every money movement.

    A Booking.confirm() writes a REVENUE row.
    An Expense.save() writes an EXPENSE row.
    A Payment writes a REVENUE row (cash actually received).
    A Refund writes an EXPENSE row (money returned).

    Nothing in the financial reports reads Booking / Expense directly —
    they all read LedgerEntry so the totals can never drift.
    """

    KIND = [
        ('revenue',   'Revenue'),
        ('expense',   'Expense'),
        ('vat',       'VAT'),
        ('refund',    'Refund'),
        ('adjustment','Adjustment'),
    ]

    # Where did this row come from?
    SOURCE = [
        ('booking',   'Booking'),
        ('payment',   'Payment'),
        ('expense',   'Expense'),
        ('invoice',   'Invoice'),
        ('manual',    'Manual entry'),
        ('refund',    'Refund'),
        ('vat',       'VAT line'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_ledger_entries',
    )
    property = models.ForeignKey(
        Property, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ledger_entries',
    )

    # Type + reason
    kind = models.CharField(max_length=20, choices=KIND, default='revenue')
    source = models.CharField(max_length=20, choices=SOURCE, default='manual')
    reason = models.CharField(
        max_length=200,
        help_text='Human-readable reason, e.g. "Cleaning – Unit 4" or "Booking #1234".',
    )

    # Money
    amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text='Always positive. Use kind to decide +/- in reports.',
    )
    vat_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text='VAT portion of this entry (0 if VAT is disabled).',
    )
    currency = models.CharField(max_length=8, default='KES')

    # Links back to the originating object (optional)
    booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ledger_entries',
    )
    expense = models.ForeignKey(
        Expense, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ledger_entries',
    )
    payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ledger_entries',
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ledger_entries',
    )

    # Timestamps — when did the money actually move?
    occurred_at = models.DateTimeField(
        default=timezone.now,
        help_text='When the money actually moved (not when the row was created).',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['organization', 'occurred_at']),
            models.Index(fields=['organization', 'kind', 'occurred_at']),
            models.Index(fields=['property', 'occurred_at']),
            models.Index(fields=['source']),
        ]
        verbose_name_plural = 'Ledger entries'

    def __str__(self):
        sign = '+' if self.kind == 'revenue' else '−'
        return f"{sign}{self.amount} · {self.reason} ({self.get_kind_display()})"

    # ---- Signed helpers used by reports ----------------------------
    @builtins.property
    def signed_amount(self):
        """Revenue/VAT are +, Expense/Refund are −."""
        if self.kind in ('revenue', 'vat'):
            return self.amount
        return -self.amount

    @builtins.property
    def net_amount(self):
        """Amount minus VAT — what actually hits P&L."""
        return self.signed_amount - self.vat_amount
    
    
    
# bnb/models.py — append

class BnbFinancialSettings(models.Model):
    """
    Per-organization financial preferences. One row per org.

    VAT is OFF by default — it's entirely optional. When enabled,
    the rate is applied to revenue lines at post time.
    """
    organization = models.OneToOneField(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='bnb_financial_settings',
    )

    # ---- VAT (optional) ----
    vat_enabled = models.BooleanField(
        default=False,
        help_text='Turn VAT tracking on/off for this organization.',
    )
    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='VAT percentage, e.g. 16 for 16%. Only used if VAT is enabled.',
    )
    vat_label = models.CharField(
        max_length=20, default='VAT',
        help_text='Label shown in UI, e.g. "VAT", "GST", "Sales Tax".',
    )
    vat_inclusive = models.BooleanField(
        default=True,
        help_text='If true, prices already include VAT. If false, VAT is added on top.',
    )

    # ---- Reporting defaults ----
    default_currency = models.CharField(max_length=8, default='KES')
    fiscal_year_start_month = models.PositiveSmallIntegerField(
        default=1,
        help_text='1 = January. Used for yearly filters.',
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'BnB financial settings'

    def __str__(self):
        return f"Financial settings — {self.organization}"

    def calculate_vat(self, gross_amount):
        """
        Return (net, vat). Respects vat_inclusive.
        If VAT is disabled, returns (gross, 0).
        """
        if not self.vat_enabled or not self.vat_rate:
            return gross_amount, Decimal('0.00')
        rate = self.vat_rate / Decimal('100')
        if self.vat_inclusive:
            net = gross_amount / (1 + rate)
            return net.quantize(Decimal('0.01')), (gross_amount - net).quantize(Decimal('0.01'))
        vat = (gross_amount * rate).quantize(Decimal('0.01'))
        return gross_amount, vat


def get_financial_settings(org):
    """Helper — returns the org's settings, creating defaults if needed."""
    if org is None:
        return None
    obj, _ = BnbFinancialSettings.objects.get_or_create(organization=org)
    return obj