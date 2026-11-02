# payments/models.py
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


def _gen_reference():
    return 'MPAY-' + uuid.uuid4().hex[:8].upper()


class PaymentAttempt(models.Model):
    METHOD_CHOICES = [
        ('mpesa', 'M-Pesa'),
        ('card',  'Card'),
        ('cash',  'Cash (recorded by business)'),
    ]
    STATUS_CHOICES = [
        ('pending',    'Pending'),
        ('processing', 'Processing'),
        ('succeeded',  'Succeeded'),
        ('failed',     'Failed'),
        ('cancelled',  'Cancelled'),
        ('refunded',   'Refunded'),
    ]
    POLICY_CHOICES = [
        ('pay_now',           'Pay now (online)'),
        ('pay_on_arrival',    'Pay on arrival'),
        ('pay_on_delivery',   'Pay on delivery'),
        ('pay_on_completion', 'Pay on completion'),
        ('pay_deposit',       'Deposit only'),
    ]

    reference = models.CharField(
        max_length=40, unique=True, default=_gen_reference, editable=False,
    )
    guest_booking = models.ForeignKey(
        'guestaccount.GuestBooking', on_delete=models.CASCADE,
        related_name='payment_attempts',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='payment_attempts',
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='payment_attempts_recorded',
        help_text='Staff member who recorded a cash payment.',
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=6, default='KES')

    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='mpesa')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Copied from listing at creation time
    policy = models.CharField(
        max_length=30, choices=POLICY_CHOICES, default='pay_now',
    )
    is_deposit = models.BooleanField(
        default=False, help_text='True when this is the deposit portion of a pay_deposit policy.',
    )
    deposit_percent = models.PositiveIntegerField(default=0)

    # M-Pesa specific
    mpesa_phone = models.CharField(max_length=30, blank=True)
    mpesa_checkout_request_id = models.CharField(max_length=80, blank=True, db_index=True)
    mpesa_merchant_request_id = models.CharField(max_length=80, blank=True)
    mpesa_receipt = models.CharField(max_length=80, blank=True)
    mpesa_result_code = models.CharField(max_length=20, blank=True)
    mpesa_result_description = models.CharField(max_length=255, blank=True)

    provider_payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    paid_in_full_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['guest_booking', 'status']),
            models.Index(fields=['mpesa_checkout_request_id']),
            models.Index(fields=['method', 'status']),
        ]

    def __str__(self):
        return f"{self.reference} · {self.get_method_display()} · {self.get_status_display()}"

    @property
    def is_paid(self):
        return self.status == 'succeeded'

    # ------------------------------------------------------------------
    # Lifecycle (call payments.services for the full transaction)
    # ------------------------------------------------------------------
    def mark_succeeded(self, provider_receipt='', extra=None):
        self.status = 'succeeded'
        self.completed_at = timezone.now()
        if provider_receipt:
            self.mpesa_receipt = provider_receipt
        if extra:
            self.provider_payload = {**(self.provider_payload or {}), **extra}
        self.save()
        return self

    def mark_failed(self, reason='', extra=None):
        self.status = 'failed'
        self.completed_at = timezone.now()
        if reason:
            self.mpesa_result_description = reason[:255]
        if extra:
            self.provider_payload = {**(self.provider_payload or {}), **extra}
        self.save()
        return self

    def mark_refunded(self, note=''):
        self.status = 'refunded'
        if note:
            self.provider_payload = {**(self.provider_payload or {}), 'refund_note': note}
        self.save()


class Receipt(models.Model):
    number = models.CharField(max_length=40, unique=True, editable=False)
    guest_booking = models.ForeignKey(
        'guestaccount.GuestBooking', on_delete=models.PROTECT,
        related_name='receipts',
    )
    payment_attempt = models.ForeignKey(
        PaymentAttempt, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='receipts',
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=6, default='KES')

    # Frozen snapshots
    business_name = models.CharField(max_length=200, blank=True)
    customer_name = models.CharField(max_length=200, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)

    description = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issued_at']
        indexes = [models.Index(fields=['guest_booking'])]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            today = timezone.now().strftime('%Y%m%d')
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            n = Receipt.objects.filter(issued_at__gte=today_start).count() + 1
            self.number = f"RCPT-{today}-{n:04d}"
        if self.guest_booking_id:
            gb = self.guest_booking
            if not self.business_name:
                self.business_name = gb.organization.name
            if not self.customer_name:
                self.customer_name = gb.customer_name
            if not self.customer_email:
                self.customer_email = gb.customer_email
            if not self.customer_phone:
                self.customer_phone = gb.customer_phone
            if not self.description:
                self.description = gb.listing.title
        super().save(*args, **kwargs)