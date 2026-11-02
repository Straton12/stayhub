# notifications/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone


class NotificationLog(models.Model):
    CHANNEL_CHOICES = [
        ('email', 'Email'),
        ('sms',   'SMS'),
        ('inapp', 'In-app'),
    ]
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('sent',   'Sent'),
        ('failed', 'Failed'),
        ('read',   'Read'),         # NEW — for in-app only
    ]
    PRIORITY_CHOICES = [
        ('low',    'Low'),
        ('normal', 'Normal'),
        ('high',   'High'),
    ]

    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='queued')
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default='normal',
    )

    # Who it's for
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='notification_logs',
    )
    recipient_organization = models.ForeignKey(
        'accounts.Organization', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='notification_logs',
    )
    to_email = models.EmailField(blank=True)
    to_phone = models.CharField(max_length=30, blank=True)

    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)

    # Event metadata
    event = models.CharField(max_length=80, blank=True, db_index=True)
    kind = models.CharField(
        max_length=40, blank=True, db_index=True,
        help_text='Broad bucket: booking / payment / review / referral / account / listing.',
    )
    related_object_repr = models.CharField(max_length=200, blank=True)

    # Canonical booking link
    guest_booking = models.ForeignKey(
        'guestaccount.GuestBooking', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='notifications',
    )

    # Error + retry
    error = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient_organization', 'channel', 'read_at']),
            models.Index(fields=['recipient_user', 'channel', 'read_at']),
            models.Index(fields=['event', 'status']),
        ]

    def __str__(self):
        return f"{self.channel} · {self.event or 'event'} · {self.status}"

    # ------------------------------------------------------------------
    # Derived
    # ------------------------------------------------------------------
    @property
    def is_read(self):
        return self.read_at is not None

    @property
    def is_failed(self):
        return self.status == 'failed'

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def mark_read(self):
        if not self.read_at:
            self.read_at = timezone.now()
            if self.status == 'sent':
                self.status = 'read'
            self.save(update_fields=['read_at', 'status'])
        return self

    def mark_sent(self, provider_id=''):
        self.status = 'sent'
        self.sent_at = timezone.now()
        if provider_id:
            self.error = provider_id
        self.save(update_fields=['status', 'sent_at', 'error'])

    def mark_failed(self, reason=''):
        self.status = 'failed'
        self.error = reason or 'Unknown error'
        self.retry_count = (self.retry_count or 0) + 1
        self.save(update_fields=['status', 'error', 'retry_count'])


# ---------------------------------------------------------------------------
# Convenience creator — used by every app in the project
# ---------------------------------------------------------------------------
def notify(
    *,
    event,
    kind='',
    subject='',
    body='',
    recipient_user=None,
    recipient_organization=None,
    to_email='',
    to_phone='',
    guest_booking=None,
    channel='inapp',
    status='sent',
    priority='normal',
    related_object_repr='',
):
    """
    Single entry point for every app. Returns the NotificationLog instance.
    Safe to call from anywhere — never raises.
    """
    try:
        log = NotificationLog.objects.create(
            channel=channel,
            status=status,
            priority=priority,
            recipient_user=recipient_user,
            recipient_organization=recipient_organization,
            to_email=to_email,
            to_phone=to_phone,
            subject=subject,
            body=body,
            event=event,
            kind=kind,
            related_object_repr=related_object_repr,
            guest_booking=guest_booking,
        )
        if channel == 'inapp' and status == 'sent':
            log.sent_at = timezone.now()
            log.save(update_fields=['sent_at'])
        return log
    except Exception:
        return None