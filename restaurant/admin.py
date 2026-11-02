# restaurant/admin.py
"""
Admin configuration for the restaurant app.

Key design notes after the marketplace-publishing pivot:

  • MenuItem has NO marketplace publishing fields any more
    (no `listing`, no `payment_policy`, no `service_fee_percent`, …).
  • `listing` is a read-only @property on MenuItem (resolves via
    RestaurantProfile) and therefore CANNOT appear in `autocomplete_fields`,
    `list_display`, `fields`, `fieldsets`, or `list_filter`.
  • Marketplace publishing lives entirely on RestaurantProfileAdmin.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    GoodsReceivedLine,
    GoodsReceivedNote,
    MenuItem,
    Order,
    OrderItem,
    PurchaseOrder,
    PurchaseOrderLine,
    Receipt,
    RecipeLine,
    Reservation,
    RestaurantProfile,
    StockItem,
    StockMovement,
    Supplier,
)


# ============================================================
#  INLINES
# ============================================================
class RecipeLineInline(admin.TabularInline):
    model = RecipeLine
    extra = 1
    autocomplete_fields = ['stock_item']
    fields = ('stock_item', 'quantity', 'notes', 'line_cost_display')
    readonly_fields = ('line_cost_display',)

    @admin.display(description='Line cost')
    def line_cost_display(self, obj):
        if not obj.pk:
            return '—'
        return obj.line_cost


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('menu_item', 'name_snapshot', 'unit_price',
              'quantity', 'notes', 'line_total_display')
    readonly_fields = ('line_total_display',)
    autocomplete_fields = ['menu_item']

    @admin.display(description='Line total')
    def line_total_display(self, obj):
        if not obj.pk:
            return '—'
        return obj.line_total


class ReservationInline(admin.TabularInline):
    model = Reservation
    extra = 0
    fields = ('customer_name', 'guests', 'reservation_time',
              'status', 'table_preference')
    show_change_link = True


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 1
    autocomplete_fields = ['stock_item']
    fields = ('stock_item', 'quantity', 'unit_cost',
              'received_quantity', 'line_total_display',
              'outstanding_display')
    readonly_fields = ('received_quantity',
                       'line_total_display', 'outstanding_display')

    @admin.display(description='Line total')
    def line_total_display(self, obj):
        if not obj.pk:
            return '—'
        return obj.line_total

    @admin.display(description='Outstanding')
    def outstanding_display(self, obj):
        if not obj.pk:
            return '—'
        return obj.outstanding_quantity


class GoodsReceivedLineInline(admin.TabularInline):
    model = GoodsReceivedLine
    extra = 0
    autocomplete_fields = ['purchase_order_line']
    fields = ('purchase_order_line', 'quantity_received', 'line_total_display')
    readonly_fields = ('line_total_display',)

    @admin.display(description='Line total')
    def line_total_display(self, obj):
        if not obj.pk:
            return '—'
        return obj.line_total


# ============================================================
#  RESTAURANT PROFILE  —  the ONE marketplace listing per restaurant
# ============================================================
@admin.register(RestaurantProfile)
class RestaurantProfileAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'organization', 'publish_to_marketplace',
        'publish_status_badge', 'is_open_now', 'price_range',
        'menu_count_display', 'updated_at',
    )
    list_filter = (
        'publish_to_marketplace', 'is_open_now',
        'price_range', 'payment_policy', 'cancellation_policy',
        'organization',
    )
    search_fields = ('name', 'organization__name', 'city', 'address', 'cuisine')
    autocomplete_fields = ['organization', 'listing']
    readonly_fields = (
        'created_at', 'updated_at',
        'publish_status_badge', 'gallery_preview',
    )
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Brand', {
            'fields': ('organization', 'listing', 'name', 'tagline',
                       'short_description', 'description',
                       'logo', 'cover_image', 'gallery_preview',
                       'gallery_images'),
        }),
        ('Location', {
            'fields': ('address', 'city', 'location_label',
                       'latitude', 'longitude'),
        }),
        ('Contact', {
            'fields': ('phone', 'email', 'whatsapp'),
        }),
        ('Socials', {
            'fields': ('website', 'facebook', 'instagram',
                       'twitter', 'tiktok', 'youtube'),
            'classes': ('collapse',),
        }),
        ('Commercial', {
            'fields': ('cuisine', 'price_range', 'min_order_amount',
                       'delivery_fee', 'delivery_radius_km',
                       'average_prep_time'),
        }),
        ('Hours', {
            'fields': ('opening_hours', 'is_open_now'),
        }),
        ('Marketplace publishing', {
            'fields': ('publish_to_marketplace', 'publish_status_badge',
                       'payment_policy', 'deposit_percent',
                       'service_fee_percent', 'cancellation_policy',
                       'house_rules'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Status')
    def publish_status_badge(self, obj):
        if not obj or not obj.pk:
            return '—'
        color = {
            'green': '#10b981', 'yellow': '#f59e0b',
            'red': '#ef4444', 'gray': '#94a3b8',
        }.get(obj.publish_status_color, '#94a3b8')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;font-weight:600;">'
            '{}</span>',
            color, obj.publish_status_label,
        )

    @admin.display(description='Menu items')
    def menu_count_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return f"{obj.live_menu_count} live / {obj.menu_count} total"

    @admin.display(description='Gallery preview')
    def gallery_preview(self, obj):
        if not obj or not obj.pk or not obj.gallery_images:
            return '—'
        imgs = ''.join(
            f'<img src="{u}" style="height:60px;margin-right:6px;'
            f'border-radius:6px;" />'
            for u in obj.gallery_image_urls
        )
        return format_html('<div>{}</div>', format_html(imgs))


# ============================================================
#  MENU  —  `listing` is a @property, so it MUST NOT appear here
# ============================================================
@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'organization', 'category', 'price',
        'is_available', 'is_vegetarian', 'is_spicy',
        'publish_status_badge',
    )
    list_filter = ('organization', 'category', 'is_available',
                   'is_vegetarian', 'is_spicy')
    search_fields = ('name', 'description', 'allergens')
    autocomplete_fields = ['organization']
    readonly_fields = (
        'created_at', 'updated_at',
        'publish_status_badge', 'recipe_cost_display',
        'effective_cost_display', 'margin_display',
    )
    date_hierarchy = 'created_at'
    inlines = [RecipeLineInline]

    fieldsets = (
        ('Identity', {
            'fields': ('organization', 'name', 'category', 'is_available'),
        }),
        ('Pricing', {
            'fields': ('price', 'cost_price',
                       'recipe_cost_display', 'effective_cost_display',
                       'margin_display'),
        }),
        ('Content', {
            'fields': ('short_description', 'description',
                       'cover_image_url', 'preparation_time',
                       'is_vegetarian', 'is_spicy', 'allergens'),
        }),
        ('Marketplace (read-only)', {
            'fields': ('publish_status_badge',),
            'description': (
                'Publishing is controlled on the Restaurant Profile. '
                'This dish appears in the storefront whenever the '
                'restaurant is published AND this dish is available.'
            ),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['make_available', 'make_unavailable']

    @admin.display(description='Marketplace status')
    def publish_status_badge(self, obj):
        if not obj or not obj.pk:
            return '—'
        color = {
            'green': '#10b981', 'yellow': '#f59e0b',
            'red': '#ef4444', 'gray': '#94a3b8',
        }.get(obj.publish_status_color, '#94a3b8')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;font-weight:600;">'
            '{}</span>',
            color, obj.publish_status_label,
        )

    @admin.display(description='Recipe cost')
    def recipe_cost_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.recipe_cost

    @admin.display(description='Effective cost')
    def effective_cost_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.effective_cost

    @admin.display(description='Margin')
    def margin_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return f"{obj.margin:,.2f} ({obj.margin_percent:.1f}%)"

    @admin.action(description='Mark selected as available')
    def make_available(self, request, queryset):
        n = queryset.update(is_available=True)
        self.message_user(request, f'{n} item(s) available.')

    @admin.action(description='Mark selected as unavailable')
    def make_unavailable(self, request, queryset):
        n = queryset.update(is_available=False)
        self.message_user(request, f'{n} item(s) unavailable.')


@admin.register(RecipeLine)
class RecipeLineAdmin(admin.ModelAdmin):
    list_display = ('menu_item', 'stock_item', 'quantity',
                    'line_cost_display')
    search_fields = ('menu_item__name', 'stock_item__name')
    autocomplete_fields = ['menu_item', 'stock_item']

    @admin.display(description='Line cost')
    def line_cost_display(self, obj):
        return obj.line_cost


# ============================================================
#  ORDER
# ============================================================
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'reference_display', 'customer_name', 'organization',
        'order_type', 'status', 'payment_status',
        'total_amount', 'balance_display', 'source', 'created_at',
    )
    list_filter = ('status', 'payment_status', 'order_type',
                   'source', 'organization')
    search_fields = ('customer_name', 'customer_phone', 'customer_address')
    autocomplete_fields = ['organization', 'listing', 'guest_booking']
    readonly_fields = ('reference_display', 'balance_display',
                       'created_at', 'updated_at', 'delivered_at',
                       'subtotal', 'payment_status')
    inlines = [OrderItemInline]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Identity', {
            'fields': ('organization', 'listing', 'guest_booking',
                       'customer_name', 'customer_phone', 'customer_address'),
        }),
        ('Order', {
            'fields': ('order_type', 'status', 'source', 'payment_policy',
                       'special_instructions', 'notes'),
        }),
        ('Money', {
            'fields': ('subtotal', 'delivery_fee', 'total_amount',
                       'amount_paid', 'balance_display', 'payment_status'),
        }),
        ('Timing', {
            'fields': ('scheduled_for', 'delivered_at'),
        }),
        ('Timestamps', {
            'fields': ('reference_display', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['mark_preparing', 'mark_ready', 'mark_delivered',
               'mark_cancelled']

    @admin.display(description='Reference')
    def reference_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.reference

    @admin.display(description='Balance')
    def balance_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.balance

    def _bulk_status(self, request, queryset, status):
        n = 0
        for o in queryset:
            try:
                o.mark_status(status)
                n += 1
            except Exception:
                pass
        self.message_user(request, f'{n} order(s) marked {status}.')

    @admin.action(description='Mark selected → preparing')
    def mark_preparing(self, request, queryset):
        self._bulk_status(request, queryset, 'preparing')

    @admin.action(description='Mark selected → ready')
    def mark_ready(self, request, queryset):
        self._bulk_status(request, queryset, 'ready')

    @admin.action(description='Mark selected → delivered')
    def mark_delivered(self, request, queryset):
        self._bulk_status(request, queryset, 'delivered')

    @admin.action(description='Mark selected → cancelled')
    def mark_cancelled(self, request, queryset):
        self._bulk_status(request, queryset, 'cancelled')


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'menu_item', 'name_snapshot',
                    'unit_price', 'quantity', 'line_total_display')
    search_fields = ('name_snapshot', 'order__customer_name')
    autocomplete_fields = ['order', 'menu_item']

    @admin.display(description='Line total')
    def line_total_display(self, obj):
        return obj.line_total


# ============================================================
#  RESERVATION
# ============================================================
@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        'reference_display', 'customer_name', 'organization',
        'guests', 'reservation_time', 'status',
    )
    list_filter = ('status', 'organization', 'reservation_time')
    search_fields = ('customer_name', 'customer_phone', 'customer_email')
    autocomplete_fields = ['organization', 'listing', 'guest_booking']
    readonly_fields = ('reference_display', 'created_at', 'updated_at')
    date_hierarchy = 'reservation_time'

    actions = ['mark_confirmed', 'mark_seated',
               'mark_completed', 'mark_cancelled']

    @admin.display(description='Reference')
    def reference_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.reference

    def _bulk_status(self, request, queryset, status):
        n = 0
        for r in queryset:
            try:
                r.mark_status(status)
                n += 1
            except Exception:
                pass
        self.message_user(request, f'{n} reservation(s) marked {status}.')

    @admin.action(description='Mark selected → confirmed')
    def mark_confirmed(self, request, queryset):
        self._bulk_status(request, queryset, 'confirmed')

    @admin.action(description='Mark selected → seated')
    def mark_seated(self, request, queryset):
        self._bulk_status(request, queryset, 'seated')

    @admin.action(description='Mark selected → completed')
    def mark_completed(self, request, queryset):
        self._bulk_status(request, queryset, 'completed')

    @admin.action(description='Mark selected → cancelled')
    def mark_cancelled(self, request, queryset):
        self._bulk_status(request, queryset, 'cancelled')


# ============================================================
#  SUPPLIER
# ============================================================
@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'phone', 'supplies',
                    'is_active', 'balance_owed_display', 'created_at')
    list_filter = ('organization', 'is_active')
    search_fields = ('name', 'phone', 'email', 'supplies')
    autocomplete_fields = ['organization']
    readonly_fields = ('created_at', 'updated_at',
                       'balance_owed_display', 'total_purchased_display')

    @admin.display(description='Balance owed')
    def balance_owed_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.balance_owed

    @admin.display(description='Total purchased')
    def total_purchased_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.total_purchased


# ============================================================
#  STOCK ITEMS & MOVEMENTS
# ============================================================
@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'category', 'unit',
                    'unit_cost', 'current_stock_display',
                    'reorder_level', 'is_low_stock_display', 'is_active')
    list_filter = ('category', 'is_active', 'organization')
    search_fields = ('name', 'sku', 'notes')
    autocomplete_fields = ['organization']
    readonly_fields = ('current_stock_display', 'stock_value_display',
                       'is_low_stock_display', 'is_out_of_stock_display',
                       'created_at', 'updated_at')

    fieldsets = (
        ('Identity', {
            'fields': ('organization', 'name', 'sku', 'category', 'unit',
                       'is_active'),
        }),
        ('Stock', {
            'fields': ('unit_cost', 'reorder_level',
                       'current_stock_display', 'stock_value_display',
                       'is_low_stock_display', 'is_out_of_stock_display'),
        }),
        ('Notes', {
            'fields': ('notes',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Current stock')
    def current_stock_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return f"{obj.current_stock} {obj.unit}"

    @admin.display(description='Stock value')
    def stock_value_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.stock_value

    @admin.display(description='Low stock?', boolean=True)
    def is_low_stock_display(self, obj):
        if not obj or not obj.pk:
            return False
        return obj.is_low_stock

    @admin.display(description='Out of stock?', boolean=True)
    def is_out_of_stock_display(self, obj):
        if not obj or not obj.pk:
            return False
        return obj.is_out_of_stock


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('stock_item', 'movement_type', 'quantity',
                    'unit_cost', 'total_cost_display',
                    'created_by', 'created_at')
    list_filter = ('movement_type', 'organization')
    search_fields = ('stock_item__name', 'reason')
    autocomplete_fields = ('organization', 'stock_item',
                           'purchase_order', 'order', 'created_by')
    readonly_fields = ('quantity_signed', 'total_cost_display',
                       'created_at')
    date_hierarchy = 'created_at'

    @admin.display(description='Total cost')
    def total_cost_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.total_cost


# ============================================================
#  PROCUREMENT
# ============================================================
@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('reference', 'organization', 'supplier', 'status',
                    'order_date', 'expected_date', 'total_amount',
                    'paid_amount', 'balance_display', 'received_at')
    list_filter = ('status', 'organization', 'supplier')
    search_fields = ('reference', 'supplier__name', 'notes')
    autocomplete_fields = ['organization', 'supplier', 'created_by']
    inlines = [PurchaseOrderLineInline]
    readonly_fields = ('reference', 'subtotal', 'total_amount',
                       'balance_display', 'created_at', 'updated_at',
                       'received_at')
    date_hierarchy = 'order_date'

    @admin.display(description='Balance')
    def balance_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.balance


@admin.register(PurchaseOrderLine)
class PurchaseOrderLineAdmin(admin.ModelAdmin):
    list_display = ('purchase_order', 'stock_item', 'quantity',
                    'unit_cost', 'received_quantity',
                    'line_total_display', 'outstanding_display',
                    'is_fully_received')
    list_filter = ('purchase_order__status',)
    search_fields = ('stock_item__name', 'purchase_order__reference')
    autocomplete_fields = ['purchase_order', 'stock_item']
    readonly_fields = ('line_total_display', 'outstanding_display',
                       'is_fully_received')

    @admin.display(description='Line total')
    def line_total_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.line_total

    @admin.display(description='Outstanding')
    def outstanding_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.outstanding_quantity


@admin.register(GoodsReceivedNote)
class GoodsReceivedNoteAdmin(admin.ModelAdmin):
    list_display = ('reference', 'purchase_order', 'received_date',
                    'total_value_display', 'received_by', 'created_at')
    list_filter = ('received_date',)
    search_fields = ('reference', 'purchase_order__reference')
    autocomplete_fields = ['purchase_order', 'received_by']
    inlines = [GoodsReceivedLineInline]
    readonly_fields = ('reference', 'total_value_display', 'created_at')
    date_hierarchy = 'received_date'

    @admin.display(description='Total value')
    def total_value_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.total_value


@admin.register(GoodsReceivedLine)
class GoodsReceivedLineAdmin(admin.ModelAdmin):
    list_display = ('grn', 'purchase_order_line', 'quantity_received',
                    'unit_cost', 'line_total_display')
    autocomplete_fields = ['grn', 'purchase_order_line']
    readonly_fields = ('unit_cost', 'line_total_display')

    @admin.display(description='Line total')
    def line_total_display(self, obj):
        if not obj or not obj.pk:
            return '—'
        return obj.line_total


# ============================================================
#  RECEIPTS
# ============================================================
@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('number', 'organization', 'order', 'amount',
                    'method', 'reference', 'issued_by', 'issued_at')
    list_filter = ('method', 'organization')
    search_fields = ('number', 'customer_name', 'customer_phone', 'reference')
    autocomplete_fields = ['organization', 'order', 'issued_by']
    readonly_fields = (
        'number', 'issued_at',
        'business_name', 'business_phone',
        'customer_name', 'customer_phone',
    )
    date_hierarchy = 'issued_at'