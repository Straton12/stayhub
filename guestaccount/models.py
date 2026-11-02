# guestaccount/models.py
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


# ============================================================
#  GUEST PROFILE
# ============================================================
class GuestProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='guest_profile',
    )
    country = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    marketing_opt_in = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Guest: {self.user}"


# ============================================================
#  GUEST BOOKING
# ============================================================
class GuestBooking(models.Model):
    """
    The single source of truth for a guest's booking / order / reservation.

    Money model
    -----------
    • stays / tours / laundry  →  price per night × nights
    • food / transport         →  price × quantity

    The `billing_unit` field records which of the two applies, so the
    invoice is always reproducible.

    Service fee is DISABLED — total_amount == subtotal.

    Date-range locking
    ------------------
    • On create: NO lock is created (status='pending')
    • On `mark_confirmed()`: a `ListingAvailabilityBlock` with status
      `confirmed` is created for [start_date, end_date).
    • On `mark_cancelled()` / `mark_completed()`: the block is released.
    • Only the exact date range is locked — future dates stay open.
    """

    STATUS_CHOICES = [
        ('pending',     'Pending payment'),
        ('confirmed',   'Confirmed'),
        ('in_progress', 'In progress'),
        ('completed',   'Completed'),
        ('cancelled',   'Cancelled'),
        ('refunded',    'Refunded'),
        ('no_show',     'No-show'),
    ]
    KIND_CHOICES = [
        ('stay',      'Stay'),
        ('tour',      'Tour'),
        ('food',      'Food order'),
        ('table',     'Table reservation'),
        ('laundry',   'Laundry'),
        ('transport', 'Transport'),
        ('other',     'Other'),
    ]
    PAYMENT_POLICY_CHOICES = [
        ('pay_now',           'Pay now (online)'),
        ('pay_on_arrival',    'Pay on arrival'),
        ('pay_on_delivery',   'Pay on delivery'),
        ('pay_on_completion', 'Pay on completion'),
        ('pay_deposit',       'Pay deposit now, rest later'),
    ]
    BILLING_UNIT_CHOICES = [
        ('per_night', 'Per night (date range)'),
        ('per_item',  'Per item / per person'),
    ]

    # ---------- Who / what ----------
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='guest_bookings',
    )
    listing = models.ForeignKey(
        'marketplace.Listing', on_delete=models.PROTECT,
        related_name='guest_bookings',
    )
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.PROTECT,
        related_name='guest_bookings',
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='stay')

    # Source row pointer (bnb.Booking.id, restaurant.Order.id, ...)
    source_app = models.CharField(max_length=40, blank=True)
    source_model = models.CharField(max_length=40, blank=True)
    source_id = models.PositiveIntegerField(null=True, blank=True)

    # ---------- Customer snapshot ----------
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)

    # ---------- Dates ----------
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # ---------- Category-specific details as JSON ----------
    details = models.JSONField(default=dict, blank=True)

    # ---------- Money ----------
    currency = models.CharField(max_length=6, default='KES')
    billing_unit = models.CharField(
        max_length=20, choices=BILLING_UNIT_CHOICES, default='per_item',
        help_text='per_night = unit_price × nights; per_item = unit_price × quantity',
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.PositiveIntegerField(default=1)
    nights = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Kept for backwards compatibility — always 0 now.
    service_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ---------- Payment policy mirror ----------
    payment_policy = models.CharField(
        max_length=30, choices=PAYMENT_POLICY_CHOICES, default='pay_now',
    )
    payment_reference = models.CharField(max_length=80, blank=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # ---------- Status ----------
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # ---------- Approval trail ----------
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='guest_bookings_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # ---------- Notes ----------
    guest_note = models.TextField(blank=True)
    org_note = models.TextField(blank=True)

    # ---------- Timestamps ----------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['listing', 'start_date', 'end_date']),
            models.Index(fields=['source_app', 'source_model', 'source_id']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"#{self.pk} {self.customer_name} → {self.listing.title}"

    # ============================================================
    #  Derived properties
    # ============================================================
    @property
    def reference(self):
        return f"SH-{self.pk:06d}"

    @property
    def balance(self):
        return (self.total_amount or Decimal('0.00')) - (self.amount_paid or Decimal('0.00'))

    @property
    def is_paid(self):
        return self.total_amount > 0 and self.amount_paid >= self.total_amount

    @property
    def requires_online_payment(self):
        return self.payment_policy in ('pay_now', 'pay_deposit')

    @property
    def is_pay_later(self):
        return self.payment_policy in (
            'pay_on_arrival', 'pay_on_delivery', 'pay_on_completion',
        )

    @property
    def is_date_range(self):
        return bool(self.start_date and self.end_date and self.start_date != self.end_date)

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

    @property
    def can_be_reviewed(self):
        return (
            self.status in ('completed', 'in_progress')
            and not self.has_review
        )

    @property
    def has_review(self):
        try:
            from marketplace.models import Review
            return Review.objects.filter(
                listing=self.listing, user=self.user,
            ).exists()
        except Exception:
            return False

    # ============================================================
    #  Money math
    # ============================================================
    def recalc_totals(self, save=True):
        """
        Recompute subtotal / total_amount from unit_price and
        (nights OR quantity), based on billing_unit.

        Service fee is DISABLED — total_amount == subtotal.
        """
        unit = Decimal(str(self.unit_price or 0))

        if self.billing_unit == 'per_night':
            # Nights: inclusive of check-in, exclusive of check-out
            if self.start_date and self.end_date:
                self.nights = max((self.end_date - self.start_date).days, 1)
            else:
                self.nights = self.nights or 1
            self.subtotal = unit * Decimal(self.nights)
        else:
            self.nights = 1
            self.subtotal = unit * Decimal(self.quantity or 1)

        # Service fee disabled — total equals subtotal
        self.service_fee = Decimal('0.00')
        self.total_amount = self.subtotal

        if save:
            self.save(update_fields=[
                'nights', 'subtotal', 'service_fee', 'total_amount',
                'billing_unit', 'updated_at',
            ])
        return self

    # ============================================================
    #  Lifecycle
    # ============================================================
    def mark_paid(self, amount, reference=''):
        amount = Decimal(str(amount or 0))
        self.amount_paid = (self.amount_paid or Decimal('0.00')) + amount
        if reference:
            self.payment_reference = reference
        if self.amount_paid >= self.total_amount and self.total_amount > 0:
            self.status = 'confirmed'
            self.paid_at = timezone.now()
            self.approved_at = self.approved_at or timezone.now()
        self.save()
        self._sync_amount_to_source()
        self._lock_listing_if_confirmed()
        return self

    def mark_confirmed(self, by_user=None):
        """
        Called when the org approves a booking (either after payment,
        or after accepting a pay-on-arrival request).
        """
        self.status = 'confirmed'
        if by_user is not None:
            self.approved_by = by_user
        if self.approved_at is None:
            self.approved_at = timezone.now()
        self.is_acknowledged = True
        self.acknowledged_at = self.acknowledged_at or timezone.now()
        self.save(update_fields=[
            'status', 'approved_by', 'approved_at',
            'is_acknowledged', 'acknowledged_at', 'updated_at',
        ])

        self._lock_listing_if_confirmed()
        self._bump_listing_booking_count()
        self._sync_status_to_source()

        self._notify_org(
            'guestaccount.booking.confirmed',
            f"Booking confirmed: {self.reference}",
            f"{self.customer_name} · {self.listing.title}",
        )
        return self

    def mark_cancelled(self):
        self.status = 'cancelled'
        self.save(update_fields=['status', 'updated_at'])
        self._release_listing_block()
        self._sync_status_to_source()
        self._notify_org(
            'guestaccount.booking.cancelled',
            f"Booking cancelled: {self.reference}",
        )

    def mark_completed(self):
        self.status = 'completed'
        self.save(update_fields=['status', 'updated_at'])
        self._release_listing_block()
        self._sync_status_to_source()
        self._notify_org(
            'guestaccount.booking.completed',
            f"Booking completed: {self.reference}",
        )

    def mark_in_progress(self):
        self.status = 'in_progress'
        self.save(update_fields=['status', 'updated_at'])
        self._sync_status_to_source()

    def acknowledge(self, org_note='', by_user=None):
        self.is_acknowledged = True
        self.acknowledged_at = timezone.now()
        if by_user is not None:
            self.approved_by = by_user
        if org_note:
            self.org_note = org_note
        self.save(update_fields=[
            'is_acknowledged', 'acknowledged_at', 'approved_by',
            'org_note', 'updated_at',
        ])

    # ============================================================
    #  Listing lock helpers
    # ============================================================
    def _lock_listing_if_confirmed(self):
        if not (self.start_date and self.end_date):
            return
        if self.status not in ('confirmed', 'in_progress'):
            return
        try:
            from marketplace.models import ListingAvailabilityBlock
            ListingAvailabilityBlock.objects.update_or_create(
                listing=self.listing,
                guest_booking=self,
                defaults={
                    'start_date': self.start_date,
                    'end_date': self.end_date,
                    'status': 'confirmed',
                },
            )
        except Exception:
            pass

    def _release_listing_block(self):
        try:
            from marketplace.models import ListingAvailabilityBlock
            ListingAvailabilityBlock.objects.filter(
                guest_booking=self,
            ).update(status='released')
        except Exception:
            pass

    def _bump_listing_booking_count(self):
        try:
            from django.db.models import F
            from marketplace.models import Listing
            Listing.objects.filter(pk=self.listing_id).update(
                booking_count=F('booking_count') + 1,
            )
        except Exception:
            pass

    # ============================================================
    #  Sync helpers
    # ============================================================
    def _sync_amount_to_source(self):
        row = self.source_row
        if row is None:
            return
        try:
            if hasattr(row, 'amount_paid'):
                row.amount_paid = self.amount_paid
                row.save(update_fields=['amount_paid'])
            if hasattr(row, 'payment_status'):
                row.save()
        except Exception:
            pass

    def _sync_status_to_source(self):
        row = self.source_row
        if row is None:
            return
        mapping = {
            'confirmed':   'confirmed',
            'in_progress': 'checked_in',
            'completed':   'checked_out',
            'cancelled':   'cancelled',
            'no_show':     'no_show',
        }
        new_status = mapping.get(self.status)
        if new_status and hasattr(row, 'status'):
            try:
                row.status = new_status
                row.save(update_fields=['status'])
            except Exception:
                pass

    # ============================================================
    #  Notifications
    # ============================================================
    def _notify_org(self, event, subject, body=''):
        try:
            from notifications.models import NotificationLog
            NotificationLog.objects.create(
                channel='inapp',
                status='sent',
                priority='high' if 'created' in event else 'normal',
                kind='booking',
                recipient_organization=self.organization,
                event=event,
                subject=subject,
                body=body or subject,
                related_object_repr=str(self),
                guest_booking=self,
                to_email=self.customer_email,
                to_phone=self.customer_phone,
            )
        except Exception:
            pass