# restaurant/models.py
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


# ============================================================
#  CONSTANTS
# ============================================================
SALE_COMPLETED_STATUSES = ('delivered',)
ORDER_OPEN_STATUSES = ('new', 'preparing', 'ready', 'out_for_delivery')
PO_OPEN_STATUSES = ('draft', 'sent', 'partial', 'received')


# ============================================================
#  RESTAURANT PROFILE  —  the ONE marketplace listing per restaurant
#  Placed FIRST so MenuItem / others can safely reference it (or not).
#  All choice lists are declared inline — no dependency on MenuItem.
# ============================================================
class RestaurantProfile(models.Model):
    """
    The restaurant's public storefront — the ONE marketplace listing
    for this business. Its MenuItems are the products displayed inside.

    Mirrors onto marketplace.Listing via _ensure_restaurant_listing(profile).
    """
    PRICE_RANGE = [
        ('budget',   'Budget (KES)'),
        ('mid',      'Mid-range (KES KES)'),
        ('premium',  'Premium (KES KES KES)'),
        ('luxury',   'Luxury (KES KES KES KES)'),
    ]
    PAYMENT_POLICY = [
        ('pay_now',           'Pay now (online)'),
        ('pay_on_delivery',   'Pay on delivery'),
        ('pay_on_pickup',     'Pay on pickup'),
        ('pay_on_completion', 'Pay on completion'),
        ('pay_deposit',       'Pay deposit now, rest later'),
    ]
    CANCELLATION_POLICY = [
        ('flexible',  'Flexible'),
        ('moderate',  'Moderate'),
        ('strict',    'Strict'),
        ('nonrefund', 'Non-refundable'),
    ]

    organization = models.OneToOneField(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='restaurant_profile',
    )
    listing = models.OneToOneField(
        'marketplace.Listing', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='restaurant_profile',
    )

    # ---------- Brand ----------
    name = models.CharField(max_length=200)
    tagline = models.CharField(max_length=200, blank=True)
    short_description = models.CharField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='restaurant/logos/', null=True, blank=True)
    cover_image = models.ImageField(upload_to='restaurant/covers/', null=True, blank=True)
    gallery_images = models.JSONField(
        default=list, blank=True,
        help_text='Up to 4 gallery image URLs. First is used as a secondary cover.',
    )

    # ---------- Location ----------
    address = models.CharField(max_length=300, blank=True)
    city = models.CharField(max_length=120, blank=True)
    location_label = models.CharField(
        max_length=200, blank=True,
        help_text='e.g. Westlands, Nairobi — shown on cards.',
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # ---------- Contact ----------
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    whatsapp = models.CharField(
        max_length=30, blank=True,
        help_text='Include country code, e.g. +254712345678.',
    )

    # ---------- Socials ----------
    website   = models.URLField(blank=True)
    facebook  = models.URLField(blank=True)
    instagram = models.URLField(blank=True)
    twitter   = models.URLField(blank=True)
    tiktok    = models.URLField(blank=True)
    youtube   = models.URLField(blank=True)

    # ---------- Commercial ----------
    cuisine = models.CharField(
        max_length=200, blank=True,
        help_text='Comma-separated, e.g. Kenyan, Italian, Fast Food',
    )
    price_range = models.CharField(max_length=20, choices=PRICE_RANGE, default='mid')
    min_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_radius_km = models.PositiveIntegerField(default=10)
    average_prep_time = models.PositiveIntegerField(
        default=30, help_text='Average minutes from order to ready.',
    )

    # ---------- Hours ----------
    opening_hours = models.JSONField(
        default=dict, blank=True,
        help_text='{"mon": "08:00-22:00", "tue": ..., "sun": "closed"}',
    )
    is_open_now = models.BooleanField(
        default=True,
        help_text='Manual override — if false, storefront shows "closed".',
    )

    # ---------- Marketplace publishing ----------
    publish_to_marketplace = models.BooleanField(default=True)
    payment_policy = models.CharField(
        max_length=20, choices=PAYMENT_POLICY, default='pay_on_delivery',
    )
    deposit_percent = models.PositiveIntegerField(default=0)
    service_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    cancellation_policy = models.CharField(
        max_length=20, choices=CANCELLATION_POLICY, default='moderate',
    )
    house_rules = models.TextField(blank=True, help_text='One per line.')

    # ---------- Timestamps ----------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Restaurant profile'
        verbose_name_plural = 'Restaurant profiles'

    def __str__(self):
        return self.name

    # ---------------------------------------------------------------
    #  Location / contact
    # ---------------------------------------------------------------
    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def gallery_image_urls(self):
        return [u for u in (self.gallery_images or []) if u][:4]

    @property
    def cuisine_list(self):
        return [c.strip() for c in (self.cuisine or '').split(',') if c.strip()]

    @property
    def house_rules_list(self):
        return [r.strip() for r in (self.house_rules or '').splitlines() if r.strip()]

    @property
    def social_links(self):
        entries = [
            ('website',   'Website',     self.website),
            ('facebook',  'Facebook',    self.facebook),
            ('instagram', 'Instagram',   self.instagram),
            ('twitter',   'X / Twitter', self.twitter),
            ('tiktok',    'TikTok',      self.tiktok),
            ('youtube',   'YouTube',     self.youtube),
        ]
        return [
            {'key': k, 'label': l, 'url': u.strip()}
            for k, l, u in entries if u and u.strip()
        ]

    @property
    def has_social_links(self):
        return bool(self.social_links)

    @property
    def has_contact(self):
        return bool(self.phone or self.email or self.whatsapp)

    @property
    def whatsapp_link(self):
        if not self.whatsapp:
            return ''
        digits = ''.join(ch for ch in self.whatsapp if ch.isdigit())
        return f"https://wa.me/{digits}" if digits else ''

    @property
    def map_embed_url(self):
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
    #  Publish status
    # ---------------------------------------------------------------
    @property
    def is_published(self):
        return bool(self.listing_id) and self.listing.is_public

    @property
    def publish_status(self):
        if not self.publish_to_marketplace:
            return 'unpublished'
        if not self.listing_id:
            return 'pending'
        if not self.listing.is_active:
            return 'hidden'
        return self.listing.status

    @property
    def publish_status_label(self):
        return {
            'unpublished': 'Not published',
            'pending':     'Pending review',
            'approved':    'Live',
            'hidden':      'Hidden',
            'rejected':    'Rejected',
            'draft':       'Draft',
        }.get(self.publish_status, self.publish_status.title())

    @property
    def publish_status_color(self):
        return {
            'unpublished': 'gray',
            'pending':     'yellow',
            'approved':    'green',
            'hidden':      'gray',
            'rejected':    'red',
            'draft':       'gray',
        }.get(self.publish_status, 'gray')

    # ---------------------------------------------------------------
    #  Menu helpers (lazy import — MenuItem is defined below)
    # ---------------------------------------------------------------
    @property
    def active_menu(self):
        from .models import MenuItem
        return MenuItem.objects.filter(
            organization=self.organization, is_available=True,
        ).order_by('category', 'name')

    @property
    def menu_count(self):
        from .models import MenuItem
        return MenuItem.objects.filter(organization=self.organization).count()

    @property
    def live_menu_count(self):
        from .models import MenuItem
        return MenuItem.objects.filter(
            organization=self.organization, is_available=True,
        ).count()


# ============================================================
#  SUPPLIERS
# ============================================================
class Supplier(models.Model):
    """
    A vendor the restaurant buys stock from.
    """
    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='suppliers',
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=300, blank=True)
    supplies = models.CharField(
        max_length=200, blank=True,
        help_text='Short description of what they supply.',
    )
    reorder_level = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
        ]

    def __str__(self):
        return self.name

    @property
    def purchase_order_count(self):
        return self.purchase_orders.count()

    @property
    def total_purchased(self):
        agg = self.purchase_orders.filter(
            status__in=('received', 'partial'),
        ).aggregate(total=Sum('total_amount'))
        return agg['total'] or Decimal('0.00')

    @property
    def total_paid(self):
        agg = self.purchase_orders.aggregate(total=Sum('paid_amount'))
        return agg['total'] or Decimal('0.00')

    @property
    def balance_owed(self):
        b = self.total_purchased - self.total_paid
        return b if b > 0 else Decimal('0.00')


# ============================================================
#  INVENTORY
# ============================================================
class StockItem(models.Model):
    """
    A raw material / ingredient / consumable the restaurant tracks.

    `current_stock` is derived from StockMovement rows — never stored
    as a column. The ledger is the single source of truth.
    """
    UNIT_CHOICES = [
        ('pcs',   'Pieces'),
        ('kg',    'Kilograms'),
        ('g',     'Grams'),
        ('l',     'Litres'),
        ('ml',    'Millilitres'),
        ('pack',  'Packs'),
        ('box',   'Boxes'),
        ('dozen', 'Dozens'),
        ('bottle','Bottles'),
        ('other', 'Other'),
    ]
    CATEGORY_CHOICES = [
        ('produce',  'Produce'),
        ('meat',     'Meat & Poultry'),
        ('seafood',  'Seafood'),
        ('dairy',    'Dairy'),
        ('dry',      'Dry Goods'),
        ('beverage', 'Beverages'),
        ('spice',    'Spices & Condiments'),
        ('packaging','Packaging'),
        ('cleaning', 'Cleaning Supplies'),
        ('other',    'Other'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='stock_items',
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(
        max_length=60, blank=True,
        help_text='Optional internal SKU.',
    )
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default='other',
    )
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='pcs')

    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Most recent purchase cost per unit.',
    )
    reorder_level = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Alert when current_stock falls to or below this.',
    )

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']
        verbose_name = 'Stock item'
        verbose_name_plural = 'Stock items'
        indexes = [
            models.Index(fields=['organization', 'is_active']),
            models.Index(fields=['organization', 'category']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'name'],
                name='unique_stock_item_per_org',
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.unit})"

    @property
    def current_stock(self):
        agg = self.movements.aggregate(total=Sum('quantity_signed'))
        return agg['total'] or Decimal('0.00')

    @property
    def stock_value(self):
        return self.current_stock * self.unit_cost

    @property
    def is_low_stock(self):
        return (
            self.reorder_level > 0
            and self.current_stock <= self.reorder_level
        )

    @property
    def is_out_of_stock(self):
        return self.current_stock <= 0

    @property
    def low_stock_delta(self):
        if not self.is_low_stock:
            return Decimal('0.00')
        d = self.reorder_level - self.current_stock
        return d if d > 0 else Decimal('0.00')


class StockMovement(models.Model):
    """
    The inventory ledger. Every change in stock is one row.

    For 'in' / 'out' / 'waste', `quantity` is stored as a positive
    number; direction is derived from `movement_type`.
    For 'adjustment', `quantity` is stored SIGNED (positive or negative)
    because it represents a delta.

    Never edit a movement once created — create a reversing movement.
    """
    MOVEMENT_TYPE = [
        ('in',         'Stock In'),
        ('out',        'Stock Out'),
        ('adjustment', 'Adjustment'),
        ('waste',      'Waste / Spoilage'),
        ('transfer',   'Transfer'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='stock_movements',
    )
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.CASCADE,
        related_name='movements',
    )

    movement_type = models.CharField(
        max_length=20, choices=MOVEMENT_TYPE, default='in',
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text='Positive for in/out/waste; signed for adjustment.',
    )
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Cost per unit at the time of the movement.',
    )

    purchase_order = models.ForeignKey(
        'restaurant.PurchaseOrder', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_movements',
    )
    order = models.ForeignKey(
        'restaurant.Order', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_movements',
    )

    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stock_movements_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stock_item', 'created_at']),
            models.Index(fields=['organization', 'movement_type']),
        ]

    def __str__(self):
        return (
            f"{self.get_movement_type_display()} {self.quantity} "
            f"{self.stock_item.unit} — {self.stock_item.name}"
        )

    @property
    def quantity_signed(self):
        """Signed quantity for aggregation. Adjustment keeps its own sign."""
        if self.movement_type == 'adjustment':
            return self.quantity
        if self.movement_type in ('in', 'transfer'):
            return self.quantity
        return -self.quantity

    @property
    def total_cost(self):
        return (self.quantity or Decimal('0.00')) * (self.unit_cost or Decimal('0.00'))


# ============================================================
#  MENU
# ============================================================
class MenuItem(models.Model):
    """
    A sellable dish.

    `MenuItem` is INTERNAL — the kitchen's menu, and the source of
    RecipeLine rows that deplete stock on sale.

    Marketplace publishing lives on `RestaurantProfile` (one per
    organization) — the single storefront listing for the restaurant.
    Dishes appear INSIDE that storefront; they do not have their own
    Listing. `listing` below is a read-only convenience that returns
    the restaurant's listing so templates can still do `item.listing`.
    """
    CATEGORY_CHOICES = [
        ('starters',  'Starters'),
        ('mains',     'Mains'),
        ('sides',     'Sides'),
        ('desserts',  'Desserts'),
        ('drinks',    'Drinks'),
        ('breakfast', 'Breakfast'),
        ('specials',  'Specials'),
        ('other',     'Other'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='menu_items',
    )

    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='mains')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Optional manual cost override. If 0, computed from recipe.',
    )

    short_description = models.CharField(max_length=280, blank=True)
    description = models.TextField(blank=True)
    cover_image_url = models.URLField(blank=True)

    preparation_time = models.PositiveIntegerField(default=15, help_text='In minutes')
    is_vegetarian = models.BooleanField(default=False)
    is_spicy = models.BooleanField(default=False)
    allergens = models.CharField(max_length=200, blank=True)

    is_available = models.BooleanField(
        default=True,
        help_text='If off, the dish is hidden from both the internal menu '
                  'and the restaurant storefront on the marketplace.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['organization', 'is_available']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return self.name

    # ---------------------------------------------------------------
    #  Listing accessor (read-only — sourced from RestaurantProfile)
    # ---------------------------------------------------------------
    @property
    def restaurant_profile(self):
        return getattr(self.organization, 'restaurant_profile', None)

    @property
    def listing(self):
        profile = self.restaurant_profile
        return profile.listing if profile else None

    # ---------------------------------------------------------------
    #  Simple helpers
    # ---------------------------------------------------------------
    @property
    def allergens_list(self):
        return [a.strip() for a in (self.allergens or '').split(',') if a.strip()]

    @property
    def order_count(self):
        return self.order_items.count()

    # ---------------------------------------------------------------
    #  Cost / margin
    # ---------------------------------------------------------------
    @property
    def recipe_cost(self):
        total = Decimal('0.00')
        for line in self.recipe_lines.all():
            total += line.quantity * (line.stock_item.unit_cost or Decimal('0.00'))
        return total

    @property
    def effective_cost(self):
        if self.cost_price and self.cost_price > 0:
            return self.cost_price
        return self.recipe_cost

    @property
    def margin(self):
        return (self.price or Decimal('0.00')) - self.effective_cost

    @property
    def margin_percent(self):
        if not self.price:
            return Decimal('0.00')
        return (self.margin / self.price) * Decimal('100')

    # ---------------------------------------------------------------
    #  Stock availability
    # ---------------------------------------------------------------
    def is_in_stock(self, quantity=1):
        for line in self.recipe_lines.select_related('stock_item'):
            needed = line.quantity * quantity
            if line.stock_item.current_stock < needed:
                return False
        return True

    # ---------------------------------------------------------------
    #  Storefront visibility (delegates to RestaurantProfile)
    # ---------------------------------------------------------------
    @property
    def is_published(self):
        profile = self.restaurant_profile
        return bool(profile and profile.is_published and self.is_available)

    @property
    def publish_status(self):
        profile = self.restaurant_profile
        if not profile or not profile.publish_to_marketplace:
            return 'unpublished'
        if not self.is_available:
            return 'hidden'
        if not profile.listing_id:
            return 'pending'
        if not profile.listing.is_active:
            return 'hidden'
        return profile.listing.status or 'pending'

    @property
    def publish_status_label(self):
        return {
            'unpublished': 'Restaurant not published',
            'pending':     'Pending review',
            'approved':    'Live',
            'hidden':      'Hidden (unavailable)',
            'rejected':    'Rejected',
            'draft':       'Draft',
        }.get(self.publish_status, self.publish_status.title())

    @property
    def publish_status_color(self):
        return {
            'unpublished': 'gray',
            'pending':     'yellow',
            'approved':    'green',
            'hidden':      'gray',
            'rejected':    'red',
            'draft':       'gray',
        }.get(self.publish_status, 'gray')

    # ---------------------------------------------------------------
    #  Effective marketplace values (sourced from RestaurantProfile)
    # ---------------------------------------------------------------
    @property
    def effective_payment_policy(self):
        profile = self.restaurant_profile
        if profile and profile.payment_policy:
            return profile.payment_policy
        return 'pay_on_delivery'

    @property
    def effective_service_fee(self):
        profile = self.restaurant_profile
        if profile and profile.service_fee_percent is not None:
            return profile.service_fee_percent
        return Decimal('0.00')

    @property
    def effective_deposit_percent(self):
        profile = self.restaurant_profile
        if profile and profile.deposit_percent is not None:
            return profile.deposit_percent
        return 0


class RecipeLine(models.Model):
    """
    One ingredient consumed by one menu item (bill of materials).
    """
    menu_item = models.ForeignKey(
        MenuItem, on_delete=models.CASCADE,
        related_name='recipe_lines',
    )
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT,
        related_name='recipe_lines',
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=1,
        help_text='Amount of stock_item consumed per one unit of menu_item.',
    )
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ('menu_item', 'stock_item')
        ordering = ['menu_item', 'stock_item']

    def __str__(self):
        return f"{self.quantity} × {self.stock_item.name} → {self.menu_item.name}"

    @property
    def line_cost(self):
        return self.quantity * (self.stock_item.unit_cost or Decimal('0.00'))

    def clean(self):
        super().clean()
        if self.menu_item_id and self.stock_item_id:
            if self.menu_item.organization_id != self.stock_item.organization_id:
                raise ValidationError(
                    'Recipe line and stock item must belong to the same organization.'
                )


# ============================================================
#  PROCUREMENT
# ============================================================
class PurchaseOrder(models.Model):
    STATUS = [
        ('draft',     'Draft'),
        ('sent',      'Sent to supplier'),
        ('partial',   'Partially received'),
        ('received',  'Fully received'),
        ('cancelled', 'Cancelled'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='purchase_orders',
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT,
        related_name='purchase_orders',
    )

    reference = models.CharField(max_length=40, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS, default='draft')

    order_date = models.DateField(default=timezone.now)
    expected_date = models.DateField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='purchase_orders_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-order_date', '-created_at']
        verbose_name = 'Purchase order'
        verbose_name_plural = 'Purchase orders'
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['supplier', 'status']),
        ]

    def __str__(self):
        return self.reference or f"PO #{self.pk} — {self.supplier.name}"

    @property
    def balance(self):
        return (self.total_amount or Decimal('0.00')) - (self.paid_amount or Decimal('0.00'))

    @property
    def is_fully_paid(self):
        return self.total_amount > 0 and self.paid_amount >= self.total_amount

    @property
    def is_open(self):
        return self.status in PO_OPEN_STATUSES

    @property
    def is_fully_received(self):
        return self.status == 'received'

    def recalc_totals(self, save=True):
        subtotal = Decimal('0.00')
        for line in self.lines.all():
            subtotal += line.line_total
        self.subtotal = subtotal
        self.total_amount = subtotal + (self.tax_amount or Decimal('0.00'))
        if save:
            self.save(update_fields=['subtotal', 'total_amount', 'updated_at'])
        return self

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = (
                f"PO-{self.organization_id:03d}-"
                f"{timezone.now().strftime('%Y%m%d%H%M%S')}"
            )
        super().save(*args, **kwargs)

    def mark_sent(self):
        self.status = 'sent'
        self.save(update_fields=['status', 'updated_at'])
        return self

    def mark_cancelled(self):
        self.status = 'cancelled'
        self.save(update_fields=['status', 'updated_at'])
        return self

    def mark_paid(self, amount):
        amount = Decimal(str(amount or 0))
        self.paid_amount = (self.paid_amount or Decimal('0.00')) + amount
        self.save(update_fields=['paid_amount', 'updated_at'])
        return self

    def refresh_status_from_lines(self):
        lines = list(self.lines.all())
        if not lines:
            return self
        all_received = all(l.is_fully_received for l in lines)
        any_received = any(l.received_quantity > 0 for l in lines)

        if all_received:
            self.status = 'received'
            if not self.received_at:
                self.received_at = timezone.now()
        elif any_received:
            self.status = 'partial'
        self.save(update_fields=['status', 'received_at', 'updated_at'])
        return self


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE,
        related_name='lines',
    )
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT,
        related_name='purchase_order_lines',
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    received_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
    )
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['purchase_order', 'id']
        verbose_name = 'Purchase order line'
        verbose_name_plural = 'Purchase order lines'

    def __str__(self):
        return f"{self.quantity} × {self.stock_item.name}"

    @property
    def line_total(self):
        return (self.quantity or Decimal('0.00')) * (self.unit_cost or Decimal('0.00'))

    @property
    def outstanding_quantity(self):
        q = (self.quantity or Decimal('0.00')) - (self.received_quantity or Decimal('0.00'))
        return q if q > 0 else Decimal('0.00')

    @property
    def is_fully_received(self):
        return self.outstanding_quantity == 0 and self.quantity > 0

    def save(self, *args, **kwargs):
        if not self.unit_cost and self.stock_item_id:
            self.unit_cost = self.stock_item.unit_cost
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.purchase_order_id and self.stock_item_id:
            if self.purchase_order.organization_id != self.stock_item.organization_id:
                raise ValidationError(
                    'Purchase order and stock item must belong to the same organization.'
                )


class GoodsReceivedNote(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE,
        related_name='receipts',
    )
    reference = models.CharField(max_length=40, blank=True, db_index=True)
    received_date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    received_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='goods_received_notes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_date', '-created_at']
        verbose_name = 'Goods received note'
        verbose_name_plural = 'Goods received notes'

    def __str__(self):
        return self.reference or f"GRN #{self.pk}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"GRN-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        super().save(*args, **kwargs)

    @property
    def total_value(self):
        agg = self.lines.aggregate(total=Sum('line_total'))
        return agg['total'] or Decimal('0.00')


class GoodsReceivedLine(models.Model):
    grn = models.ForeignKey(
        GoodsReceivedNote, on_delete=models.CASCADE,
        related_name='lines',
    )
    purchase_order_line = models.ForeignKey(
        PurchaseOrderLine, on_delete=models.PROTECT,
        related_name='grn_lines',
    )
    quantity_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['grn', 'id']
        verbose_name = 'Goods received line'
        verbose_name_plural = 'Goods received lines'

    def __str__(self):
        return f"{self.quantity_received} × {self.purchase_order_line.stock_item.name}"

    @property
    def unit_cost(self):
        return self.purchase_order_line.unit_cost

    @property
    def line_total(self):
        return (self.quantity_received or Decimal('0.00')) * self.unit_cost

    def apply(self, created_by=None):
        qty = self.quantity_received or Decimal('0.00')
        if qty <= 0:
            return

        line = self.purchase_order_line
        stock = line.stock_item

        line.received_quantity = (line.received_quantity or Decimal('0.00')) + qty
        line.save(update_fields=['received_quantity'])

        StockMovement.objects.create(
            organization=stock.organization,
            stock_item=stock,
            movement_type='in',
            quantity=qty,
            unit_cost=self.unit_cost,
            purchase_order=line.purchase_order,
            reason=f"Received via {self.grn.reference}",
            created_by=created_by or self.grn.received_by,
        )

        if self.unit_cost:
            stock.unit_cost = self.unit_cost
            stock.save(update_fields=['unit_cost', 'updated_at'])


# ============================================================
#  ORDERS
# ============================================================
class Order(models.Model):
    STATUS = [
        ('new',              'New'),
        ('preparing',        'Preparing'),
        ('ready',            'Ready'),
        ('out_for_delivery', 'Out for delivery'),
        ('delivered',        'Delivered'),
        ('cancelled',        'Cancelled'),
    ]
    TYPE = [('dine_in', 'Dine In'), ('takeaway', 'Takeaway'), ('delivery', 'Delivery')]
    SOURCE = [('direct', 'Direct'), ('marketplace', 'Marketplace')]
    PAYMENT_POLICY = [
        ('pay_now',           'Pay now'),
        ('pay_on_delivery',   'Pay on delivery'),
        ('pay_on_pickup',     'Pay on pickup'),
        ('pay_on_completion', 'Pay on completion'),
    ]
    PAYMENT_STATUS = [
        ('unpaid',  'Unpaid'),
        ('partial', 'Partially paid'),
        ('paid',    'Paid'),
        ('refunded','Refunded'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='orders',
    )
    listing = models.ForeignKey(
        'marketplace.Listing', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='restaurant_orders',
    )
    guest_booking = models.OneToOneField(
        'guestaccount.GuestBooking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='restaurant_order',
    )

    customer_name = models.CharField(max_length=200)
    customer_phone = models.CharField(max_length=30, blank=True)
    customer_address = models.CharField(max_length=300, blank=True)

    order_type = models.CharField(max_length=20, choices=TYPE, default='dine_in')
    status = models.CharField(max_length=20, choices=STATUS, default='new')
    source = models.CharField(max_length=20, choices=SOURCE, default='direct')
    payment_policy = models.CharField(
        max_length=20, choices=PAYMENT_POLICY, default='pay_on_delivery',
    )
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default='unpaid',
    )

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    special_instructions = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    scheduled_for = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['guest_booking']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Order #{self.id} - {self.customer_name}"

    # ---------------- Derived ----------------
    @property
    def reference(self):
        return f"FD-{self.pk:06d}"

    @property
    def balance(self):
        return (self.total_amount or Decimal('0.00')) - (self.amount_paid or Decimal('0.00'))

    @property
    def is_paid(self):
        return self.total_amount > 0 and self.amount_paid >= self.total_amount

    @property
    def is_revenue(self):
        return self.status in SALE_COMPLETED_STATUSES

    # ---------------- Save ----------------
    def save(self, *args, **kwargs):
        if not self.amount_paid or self.amount_paid <= 0:
            self.payment_status = 'unpaid'
        elif self.total_amount and self.amount_paid < self.total_amount:
            self.payment_status = 'partial'
        else:
            self.payment_status = 'paid'
        super().save(*args, **kwargs)

    # ---------------- Totals ----------------
    def recalc_totals(self, save=True):
        subtotal = Decimal('0.00')
        for item in self.items.all():
            subtotal += item.unit_price * item.quantity
        self.subtotal = subtotal
        self.total_amount = subtotal + (self.delivery_fee or Decimal('0.00'))
        if save:
            self.save(update_fields=['subtotal', 'total_amount', 'updated_at'])
        return self

    # ---------------- Stock depletion ----------------
    def _deplete_stock_for_item(self, order_item):
        menu_item = order_item.menu_item
        if not menu_item:
            return
        for line in menu_item.recipe_lines.select_related('stock_item'):
            qty = line.quantity * order_item.quantity
            if qty <= 0:
                continue
            StockMovement.objects.create(
                organization=self.organization,
                stock_item=line.stock_item,
                movement_type='out',
                quantity=qty,
                unit_cost=line.stock_item.unit_cost,
                order=self,
                reason=f"Sold via {self.reference}",
            )

    def _deplete_stock_for_all_items(self):
        for oi in self.items.select_related('menu_item').all():
            self._deplete_stock_for_item(oi)

    def _restore_stock_for_all_items(self):
        for mv in self.stock_movements.filter(movement_type='out'):
            StockMovement.objects.create(
                organization=self.organization,
                stock_item=mv.stock_item,
                movement_type='adjustment',
                quantity=mv.quantity,
                unit_cost=mv.unit_cost,
                order=self,
                reason=f"Reversal for cancelled {self.reference}",
            )

    # ---------------- Guest booking sync ----------------
    def _sync_guest_booking(self):
        if not self.guest_booking_id:
            return
        gb = self.guest_booking
        gb.amount_paid = self.amount_paid
        gb.status = {
            'new':              'confirmed',
            'preparing':        'in_progress',
            'ready':            'in_progress',
            'out_for_delivery': 'in_progress',
            'delivered':        'completed',
            'cancelled':        'cancelled',
        }.get(self.status, gb.status)
        gb.save(update_fields=['amount_paid', 'status', 'updated_at'])

    # ---------------- Notifications ----------------
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

    # ---------------- Lifecycle ----------------
    def mark_status(self, new_status):
        if new_status not in dict(self.STATUS):
            return
        old_status = self.status
        self.status = new_status
        if new_status == 'delivered' and not self.delivered_at:
            self.delivered_at = timezone.now()
        self.save()

        if new_status == 'delivered' and old_status != 'delivered':
            self._deplete_stock_for_all_items()

        if new_status == 'cancelled' and old_status == 'delivered':
            self._restore_stock_for_all_items()

        self._sync_guest_booking()
        self._notify(
            f'restaurant.order.{new_status}',
            f'Order {self.reference} → {new_status}',
        )

    def record_payment(self, amount, method='cash', reference='', by_user=None):
        amount = Decimal(str(amount or 0))
        if amount <= 0:
            return None
        self.amount_paid = (self.amount_paid or Decimal('0.00')) + amount
        self.save()

        receipt = None
        if self.is_paid:
            receipt = Receipt.objects.create(
                organization=self.organization,
                order=self,
                amount=self.total_amount,
                method=method,
                reference=reference,
                issued_by=by_user,
            )
        self._sync_guest_booking()
        self._notify(
            'restaurant.order.payment',
            f'Payment received for {self.reference}',
            f'Amount: {amount}',
        )
        return receipt


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(
        MenuItem, on_delete=models.PROTECT,
        related_name='order_items', null=True, blank=True,
    )
    name_snapshot = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    notes = models.CharField(max_length=200, blank=True)

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def save(self, *args, **kwargs):
        if not self.name_snapshot and self.menu_item_id:
            self.name_snapshot = self.menu_item.name
        super().save(*args, **kwargs)
        try:
            self.order.recalc_totals()
        except Exception:
            pass


# ============================================================
#  RESERVATIONS
# ============================================================
class Reservation(models.Model):
    STATUS = [
        ('pending',   'Pending'),
        ('confirmed', 'Confirmed'),
        ('seated',    'Seated'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE, related_name='reservations',
    )
    listing = models.ForeignKey(
        'marketplace.Listing', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='restaurant_reservations',
    )
    guest_booking = models.OneToOneField(
        'guestaccount.GuestBooking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='restaurant_reservation',
    )
    customer_name = models.CharField(max_length=200)
    customer_phone = models.CharField(max_length=30, blank=True)
    customer_email = models.EmailField(blank=True)

    guests = models.PositiveIntegerField(default=2)
    reservation_time = models.DateTimeField()
    table_preference = models.CharField(max_length=80, blank=True)

    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-reservation_time']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['reservation_time']),
        ]

    def __str__(self):
        return f"{self.customer_name} @ {self.reservation_time}"

    @property
    def reference(self):
        return f"RSV-{self.pk:06d}"

    def _sync_guest_booking(self):
        if not self.guest_booking_id:
            return
        gb = self.guest_booking
        gb.status = {
            'pending':   'pending',
            'confirmed': 'confirmed',
            'seated':    'in_progress',
            'completed': 'completed',
            'cancelled': 'cancelled',
        }.get(self.status, gb.status)
        gb.save(update_fields=['status', 'updated_at'])

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
        self.save(update_fields=['status', 'updated_at'])
        self._sync_guest_booking()
        self._notify(
            f'restaurant.reservation.{new_status}',
            f'Reservation {self.reference} → {new_status}',
        )


# ============================================================
#  RECEIPTING
# ============================================================
class Receipt(models.Model):
    """
    A receipt issued when an order is fully paid.
    Numbering: RCPT-YYYYMMDD-NNNN, scoped per organization per day.
    """
    PAYMENT_METHODS = [
        ('cash',   'Cash'),
        ('mpesa',  'M-Pesa'),
        ('card',   'Card'),
        ('bank',   'Bank Transfer'),
        ('other',  'Other'),
    ]

    organization = models.ForeignKey(
        'accounts.Organization', on_delete=models.CASCADE,
        related_name='restaurant_receipts',
    )
    order = models.ForeignKey(
        Order, on_delete=models.PROTECT,
        related_name='receipts',
    )

    number = models.CharField(max_length=40, unique=True, editable=False)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    method = models.CharField(
        max_length=20, choices=PAYMENT_METHODS, default='cash',
    )
    reference = models.CharField(max_length=120, blank=True)

    business_name = models.CharField(max_length=200, blank=True)
    business_phone = models.CharField(max_length=30, blank=True)
    customer_name = models.CharField(max_length=200, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)

    notes = models.TextField(blank=True)
    issued_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='restaurant_receipts_issued',
    )
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issued_at']
        indexes = [
            models.Index(fields=['organization', 'issued_at']),
            models.Index(fields=['order']),
        ]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            today = timezone.now().strftime('%Y%m%d')
            today_start = timezone.now().replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            n = (
                Receipt.objects
                .filter(organization=self.organization, issued_at__gte=today_start)
                .count() + 1
            )
            self.number = f"RCPT-{today}-{n:04d}"

        if not self.business_name and self.organization_id:
            self.business_name = self.organization.name
            self.business_phone = self.organization.phone or ''

        if self.order_id and not self.customer_name:
            self.customer_name = self.order.customer_name
            self.customer_phone = self.order.customer_phone

        super().save(*args, **kwargs)