# tours/models.py
from decimal import Decimal

from django.db import models
from django.utils import timezone


# ============================================================
#  PACKAGES
# ============================================================
class TourPackage(models.Model):
    PACKAGE_TYPES = [
        ('day_trip',  'Day Trip'),
        ('safari',    'Safari'),
        ('city_tour', 'City Tour'),
        ('multi_day', 'Multi-Day Tour'),
        ('beach',     'Beach Holiday'),
        ('adventure', 'Adventure'),
        ('cultural',  'Cultural'),
        ('other',     'Other'),
    ]
    PAYMENT_POLICY = [
        ('pay_now',           'Pay now (online)'),
        ('pay_deposit',       'Pay deposit now, rest later'),
        ('pay_on_arrival',    'Pay on arrival'),
        ('pay_on_completion', 'Pay on completion'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='tour_packages',
    )
    listing = models.OneToOneField(
        'marketplace.Listing', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tour_package',
    )

    name = models.CharField(max_length=200)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPES, default='day_trip')
    destination = models.CharField(max_length=200)
    duration_days = models.PositiveIntegerField(default=1)
    price_per_person = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    short_description = models.CharField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    cover_image_url = models.URLField(blank=True)

    highlights = models.TextField(blank=True, help_text='One per line')
    what_to_bring = models.TextField(blank=True, help_text='One per line')

    min_travellers = models.PositiveIntegerField(default=1)
    max_travellers = models.PositiveIntegerField(default=20)
    pickup_available = models.BooleanField(default=True)
    languages = models.CharField(max_length=200, blank=True, help_text='Comma-separated')

    # Marketplace defaults
    payment_policy = models.CharField(
        max_length=20, choices=PAYMENT_POLICY, default='pay_now',
    )
    deposit_percent = models.PositiveIntegerField(
        default=0, help_text='If payment_policy=pay_deposit, % due now.',
    )
    service_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=5,
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organization', 'is_active'])]

    def __str__(self):
        return self.name

    @property
    def highlights_list(self):
        return [h.strip() for h in (self.highlights or '').splitlines() if h.strip()]

    @property
    def what_to_bring_list(self):
        return [w.strip() for w in (self.what_to_bring or '').splitlines() if w.strip()]

    @property
    def languages_list(self):
        return [l.strip() for l in (self.languages or '').split(',') if l.strip()]

    @property
    def booking_count(self):
        return self.bookings.count()


# ============================================================
#  BOOKINGS
# ============================================================
class TourBooking(models.Model):
    STATUS = [
        ('pending',   'Pending'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    SOURCE = [
        ('direct',      'Direct'),
        ('agent',       'Travel Agent'),
        ('referral',    'Referral'),
        ('marketplace', 'Marketplace'),
    ]
    PAYMENT_STATUS = [
        ('unpaid',  'Unpaid'),
        ('partial', 'Partially paid'),
        ('paid',    'Paid'),
        ('refunded','Refunded'),
    ]

    package = models.ForeignKey(
        TourPackage, on_delete=models.CASCADE, related_name='bookings',
    )
    guest_booking = models.OneToOneField(
        'guestaccount.GuestBooking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tour_booking',
    )

    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)
    travellers_count = models.PositiveIntegerField(default=1)
    travel_date = models.DateField()

    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    source = models.CharField(max_length=20, choices=SOURCE, default='direct')
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default='unpaid',
    )

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(blank=True)
    special_requests = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['package', 'travel_date']),
            models.Index(fields=['guest_booking']),
        ]

    def __str__(self):
        return f"{self.customer_name} - {self.package.name}"

    @property
    def reference(self):
        return f"TR-{self.pk:06d}"

    @property
    def balance(self):
        return (self.total_amount or Decimal('0.00')) - (self.amount_paid or Decimal('0.00'))

    @property
    def is_paid(self):
        return self.total_amount > 0 and self.amount_paid >= self.total_amount

    def save(self, *args, **kwargs):
        if not self.amount_paid or self.amount_paid <= 0:
            self.payment_status = 'unpaid'
        elif self.total_amount and self.amount_paid < self.total_amount:
            self.payment_status = 'partial'
        else:
            self.payment_status = 'paid'
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------
    def _sync_guest_booking(self):
        if not self.guest_booking_id:
            return
        gb = self.guest_booking
        gb.amount_paid = self.amount_paid
        gb.status = {
            'pending':   'pending',
            'confirmed': 'confirmed',
            'completed': 'completed',
            'cancelled': 'cancelled',
        }.get(self.status, gb.status)
        gb.save(update_fields=['amount_paid', 'status', 'updated_at'])

    def _notify(self, event, subject, body=''):
        try:
            from notifications.models import NotificationLog
            NotificationLog.objects.create(
                channel='inapp',
                status='sent',
                recipient_organization=self.package.organization,
                event=event,
                subject=subject,
                body=body or subject,
                related_object_repr=str(self),
                guest_booking=self.guest_booking,
                to_email=self.customer_email,
                to_phone=self.customer_phone,
            )
        except Exception:
            pass

    def mark_status(self, new_status):
        if new_status not in dict(self.STATUS):
            return
        self.status = new_status
        self.save(update_fields=['status', 'updated_at'])
        self._sync_guest_booking()
        # Lock the departure date on the listing
        try:
            self.package.listing.availability_blocks.update_or_create(
                guest_booking=self.guest_booking,
                defaults={
                    'listing': self.package.listing,
                    'start_date': self.travel_date,
                    'end_date': self.travel_date,
                    'status': 'confirmed' if new_status in ('confirmed', 'completed') else 'released',
                },
            )
        except Exception:
            pass
        self._notify(f'tours.booking.{new_status}',
                     f'Tour booking {self.reference} → {new_status}')


# ============================================================
#  GUIDES
# ============================================================
class Guide(models.Model):
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='guides',
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    languages = models.CharField(max_length=200, blank=True)
    license_number = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def languages_list(self):
        return [l.strip() for l in (self.languages or '').split(',') if l.strip()]


# ============================================================
#  VEHICLES
# ============================================================
class Vehicle(models.Model):
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='vehicles',
    )
    name = models.CharField(max_length=120)
    plate_number = models.CharField(max_length=30, blank=True)
    capacity = models.PositiveIntegerField(default=4)
    vehicle_type = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.plate_number or 'no plate'})"