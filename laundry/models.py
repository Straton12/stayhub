# laundry/models.py
from decimal import Decimal

from django.db import models
from django.utils import timezone


class LaundryService(models.Model):
    SERVICE_TYPES = [
        ('wash_fold',  'Wash & Fold'),
        ('wash_iron',  'Wash & Iron'),
        ('dry_clean',  'Dry Cleaning'),
        ('iron_only',  'Iron Only'),
        ('bedding',    'Bedding & Duvets'),
        ('curtains',   'Curtains'),
        ('shoes',      'Shoe Cleaning'),
        ('other',      'Other'),
    ]
    PRICE_UNITS = [
        ('per_kg',   'Per kg'),
        ('per_item', 'Per item'),
        ('per_load', 'Per load'),
        ('per_set',  'Per set'),
    ]
    PAYMENT_POLICY = [
        ('pay_now',         'Pay now'),
        ('pay_on_delivery', 'Pay on delivery'),
        ('pay_on_pickup',   'Pay on pickup'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='laundry_services',
    )
    listing = models.OneToOneField(
        'marketplace.Listing', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='laundry_service',
    )

    name = models.CharField(max_length=200)
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPES, default='wash_fold')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_unit = models.CharField(max_length=20, choices=PRICE_UNITS, default='per_kg')

    short_description = models.CharField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    cover_image_url = models.URLField(blank=True)

    turnaround_hours = models.PositiveIntegerField(default=24)
    pickup_available = models.BooleanField(default=True)
    delivery_available = models.BooleanField(default=True)
    same_day = models.BooleanField(default=False)

    # Marketplace defaults
    payment_policy = models.CharField(
        max_length=20, choices=PAYMENT_POLICY, default='pay_on_delivery',
    )
    service_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=5,
        help_text='Marketplace fee added at checkout.',
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_price_unit_display()})"

    @property
    def order_count(self):
        return self.orders.count()

    @property
    def pending_count(self):
        return self.orders.exclude(status__in=['delivered', 'cancelled']).count()


class LaundryOrder(models.Model):
    STATUS = [
        ('received',         'Received'),
        ('washing',          'Washing'),
        ('ready',            'Ready'),
        ('out_for_delivery', 'Out for delivery'),
        ('delivered',        'Delivered'),
        ('cancelled',        'Cancelled'),
    ]
    SOURCE = [
        ('direct',      'Direct'),
        ('marketplace', 'Marketplace'),
    ]
    PAYMENT_POLICY = [
        ('pay_now',         'Pay now'),
        ('pay_on_delivery', 'Pay on delivery'),
        ('pay_on_pickup',   'Pay on pickup'),
    ]
    PAYMENT_STATUS = [
        ('unpaid',  'Unpaid'),
        ('partial', 'Partially paid'),
        ('paid',    'Paid'),
        ('refunded','Refunded'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='laundry_orders',
    )
    listing = models.ForeignKey(
        'marketplace.Listing', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='laundry_orders',
    )
    guest_booking = models.OneToOneField(
        'guestaccount.GuestBooking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='laundry_order',
    )
    service = models.ForeignKey(
        LaundryService, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders',
    )

    customer_name = models.CharField(max_length=200)
    customer_phone = models.CharField(max_length=30, blank=True)
    pickup_address = models.CharField(max_length=255, blank=True)
    delivery_address = models.CharField(max_length=255, blank=True)

    # Order contents snapshot
    item_description = models.TextField(blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=30, choices=STATUS, default='received')
    source = models.CharField(max_length=20, choices=SOURCE, default='direct')
    payment_policy = models.CharField(
        max_length=20, choices=PAYMENT_POLICY, default='pay_on_delivery',
    )
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default='unpaid',
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(blank=True)

    # Timing
    scheduled_pickup = models.DateTimeField(null=True, blank=True)
    scheduled_delivery = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['guest_booking']),
        ]

    def __str__(self):
        return f"Order #{self.id} - {self.customer_name}"

    @property
    def reference(self):
        return f"LD-{self.pk:06d}"

    @property
    def balance(self):
        return (self.total_amount or Decimal('0.00')) - (self.amount_paid or Decimal('0.00'))

    @property
    def is_paid(self):
        return self.total_amount > 0 and self.amount_paid >= self.total_amount

    def save(self, *args, **kwargs):
        # derive payment_status
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
            'received':         'confirmed',
            'washing':          'in_progress',
            'ready':            'in_progress',
            'out_for_delivery': 'in_progress',
            'delivered':        'completed',
            'cancelled':        'cancelled',
        }.get(self.status, gb.status)
        gb.save(update_fields=['amount_paid', 'status', 'updated_at'])

    def _notify(self, event, subject, body=''):
        try:
            from notifications.models import NotificationLog
            NotificationLog.objects.create(
                channel='inapp',
                status='sent',
                recipient_organization=self.organization,
                event=event,
                subject=subject,
                body=body or subject,
                related_object_repr=str(self),
                guest_booking=self.guest_booking,
                to_phone=self.customer_phone,
            )
        except Exception:
            pass

    def mark_status(self, new_status):
        if new_status not in dict(self.STATUS):
            return
        self.status = new_status
        if new_status == 'delivered' and not self.delivered_at:
            self.delivered_at = timezone.now()
        self.save()
        self._sync_guest_booking()
        self._notify(f'laundry.order.{new_status}',
                     f'Laundry order {self.reference} → {new_status}')


class LaundrySupply(models.Model):
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='laundry_supplies',
    )
    name = models.CharField(max_length=120)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, default='pcs')

    # Small addition — reorder hints
    reorder_level = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.unit})"