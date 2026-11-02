# network/models.py
from decimal import Decimal

from django.db import models


# ===========================================================================
#  REFERRAL
# ===========================================================================
class Referral(models.Model):
    """
    A referral between two organizations.

    Two ways referrals get created:
      • Manually — an org admin refers a guest to a partner org.
      • Automatically — the overflow matcher routes a guest to a partner
        when the original listing is already booked for the requested
        dates. These have ``is_auto=True`` and ``source='auto_overflow'``.

    The guest never sees the referral mechanics. The original org keeps
    the guest's money and pays the receiving org a commission out-of-band.
    """

    STATUS = [
        ('auto_pending', 'Auto-pending match'),    # created by matcher, awaiting accept
        ('pending',      'Pending'),               # manual referral awaiting accept
        ('accepted',     'Accepted'),
        ('completed',    'Completed'),
        ('rejected',     'Rejected'),
        ('expired',      'Expired'),
        ('no_match',     'No match found'),        # overflow matcher failed
    ]
    SOURCE = [
        ('manual',        'Manual'),
        ('marketplace',   'Marketplace'),
        ('auto_overflow', 'Auto overflow'),
    ]

    # ---------- Parties ----------
    from_org = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='referrals_sent',
    )
    to_org = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='referrals_received',
    )
    guest_booking = models.ForeignKey(
        'guestaccount.GuestBooking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='referrals',
    )

    # ---------- Guest ----------
    guest_name = models.CharField(max_length=200)
    guest_phone = models.CharField(max_length=30, blank=True)
    guest_email = models.EmailField(blank=True)

    # ---------- Service ----------
    service_needed = models.CharField(max_length=200)
    notes = models.TextField(blank=True)

    source = models.CharField(max_length=20, choices=SOURCE, default='manual')
    status = models.CharField(max_length=20, choices=STATUS, default='pending')

    # ---------- Money ----------
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Percent agreed at creation time "
                  "(from the referrer's NetworkProfile).",
    )
    commission_paid = models.BooleanField(default=False)
    commission_paid_at = models.DateTimeField(null=True, blank=True)

    # ---------- Overflow-specific ----------
    is_auto = models.BooleanField(
        default=False,
        help_text='True when created by the automatic overflow matcher.',
    )
    match_reason = models.CharField(
        max_length=20, blank=True,
        help_text='favorite | network | none',
    )
    referrer_payout = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Amount the referrer keeps after paying the referred org.',
    )

    # ---------- Lifecycle timestamps ----------
    accepted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['from_org', 'status']),
            models.Index(fields=['to_org', 'status']),
            models.Index(fields=['guest_booking']),
            models.Index(fields=['is_auto', 'status']),
        ]

    def __str__(self):
        return f"{self.from_org} → {self.to_org} ({self.guest_name})"

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------
    @property
    def reference(self):
        return f"REF-{self.pk:06d}"

    @property
    def is_open(self):
        return self.status in ('auto_pending', 'pending', 'accepted')

    @property
    def is_paid(self):
        return self.commission_paid and self.commission > 0

    @property
    def commission_due(self):
        return (
            Decimal('0.00')
            if self.commission_paid
            else (self.commission or Decimal('0.00'))
        )

    @property
    def is_self_referral(self):
        """True if no real transfer happened (e.g. no_match fallback)."""
        return self.from_org_id == self.to_org_id

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _notify(self, recipient_org, event, subject, body=''):
        try:
            from notifications.models import NotificationLog
            NotificationLog.objects.create(
                channel='inapp',
                status='sent',
                recipient_organization=recipient_org,
                event=event,
                subject=subject,
                body=body or subject,
                related_object_repr=str(self),
                guest_booking=self.guest_booking,
                to_phone=self.guest_phone,
                to_email=self.guest_email,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Guest booking sync
    # ------------------------------------------------------------------
    def _sync_guest_booking(self):
        if not self.guest_booking_id:
            return
        gb = self.guest_booking
        if self.status == 'completed' and gb.status not in ('completed', 'cancelled'):
            try:
                gb.mark_completed()
            except Exception:
                gb.status = 'completed'
                gb.save(update_fields=['status', 'updated_at'])
        elif self.status == 'rejected' and gb.status == 'pending':
            try:
                gb.mark_cancelled()
            except Exception:
                gb.status = 'cancelled'
                gb.save(update_fields=['status', 'updated_at'])

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------
    def mark_accepted(self):
        from django.utils import timezone
        self.status = 'accepted'
        self.accepted_at = timezone.now()
        self.save(update_fields=['status', 'accepted_at'])
        self._notify(
            self.from_org, 'network.referral.accepted',
            f'Referral {self.reference} accepted',
        )
        return self

    def mark_completed(self):
        from django.utils import timezone
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])
        self._sync_guest_booking()
        self._notify(
            self.from_org, 'network.referral.completed',
            f'Referral {self.reference} completed',
        )
        return self

    def mark_rejected(self):
        self.status = 'rejected'
        self.save(update_fields=['status'])
        self._sync_guest_booking()
        self._notify(
            self.from_org, 'network.referral.rejected',
            f'Referral {self.reference} rejected',
        )
        return self

    def mark_paid(self):
        from django.utils import timezone
        self.commission_paid = True
        self.commission_paid_at = timezone.now()
        self.save(update_fields=['commission_paid', 'commission_paid_at'])
        self._notify(
            self.to_org, 'network.referral.paid',
            f'Commission paid for {self.reference}',
        )
        return self


# ===========================================================================
#  NETWORK PROFILE
# ===========================================================================
class NetworkProfile(models.Model):
    """
    Per-organization settings for the partner network:
    whether they offer/accept referrals, their commission rate,
    and the categories they prefer.
    """
    organization = models.OneToOneField(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='network_profile',
    )
    tagline = models.CharField(max_length=200, blank=True)
    service_area = models.CharField(max_length=200, blank=True)

    offers_referrals = models.BooleanField(default=True)
    accepts_referrals = models.BooleanField(default=True)
    visible_to_guests = models.BooleanField(default=False)

    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=5,
        help_text='Percent of the referral value your org pays as commission.',
    )

    categories = models.CharField(
        max_length=200, blank=True,
        help_text='Comma-separated slugs, e.g. stays,tours',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['organization__name']

    def __str__(self):
        return f"Network profile: {self.organization}"

    @property
    def categories_list(self):
        return [
            c.strip()
            for c in (self.categories or '').split(',')
            if c.strip()
        ]

    def partner_listings(self, limit=12):
        """
        Approved listings from other orgs in the network — same categories
        the org prefers, if specified.
        """
        from marketplace.models import Listing
        qs = (
            Listing.objects
            .filter(
                status='approved', is_active=True,
                organization__network_joined=True,
            )
            .exclude(organization=self.organization)
            .select_related('category', 'organization')
        )
        cats = self.categories_list
        if cats:
            qs = qs.filter(category__slug__in=cats)
        return qs.order_by('-approved_at')[:limit]


# ===========================================================================
#  NETWORK FAVORITES
# ===========================================================================
class NetworkFavorite(models.Model):
    """
    Pinned partner properties that get matched first during overflow.

    When a guest books one of the org's properties but it's already
    occupied for the requested dates, the overflow matcher looks here
    first before falling back to the wider network.

    Favorites are Listing rows owned by *other* organizations —
    the org has flagged them as preferred partners.
    """
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='network_favorites',
    )
    listing = models.ForeignKey(
        'marketplace.Listing', on_delete=models.CASCADE,
        related_name='favorited_by_orgs',
    )
    priority = models.PositiveIntegerField(
        default=10,
        help_text='Lower numbers are checked first.',
    )
    notes = models.CharField(
        max_length=200, blank=True,
        help_text='Optional note about why this partner is preferred.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('organization', 'listing')
        ordering = ['priority', '-created_at']
        verbose_name = 'Network favorite'
        verbose_name_plural = 'Network favorites'

    def __str__(self):
        return f"{self.organization} ♥ {self.listing}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.listing_id and self.organization_id:
            if self.listing.organization_id == self.organization_id:
                raise ValidationError(
                    'You cannot favorite your own listing.'
                )