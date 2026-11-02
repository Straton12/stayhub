# laundry/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import LaundryService, LaundryOrder, LaundrySupply


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------
class LaundryOrderInline(admin.TabularInline):
    model = LaundryOrder
    extra = 0
    fields = ('customer_name', 'status', 'payment_status',
              'total_amount', 'amount_paid', 'created_at')
    readonly_fields = ('created_at',)
    show_change_link = True


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
@admin.register(LaundryService)
class LaundryServiceAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'organization', 'service_type', 'price', 'price_unit',
        'turnaround_hours', 'is_active', 'listing_link',
    )
    list_filter = ('organization', 'service_type', 'is_active',
                   'pickup_available', 'delivery_available', 'same_day')
    search_fields = ('name', 'description')
    autocomplete_fields = ['organization', 'listing']
    readonly_fields = ('created_at', 'updated_at')
    inlines = [LaundryOrderInline]

    fieldsets = (
        ('Identity', {
            'fields': ('organization', 'name', 'service_type', 'listing'),
        }),
        ('Pricing', {
            'fields': ('price', 'price_unit', 'service_fee_percent'),
        }),
        ('Content', {
            'fields': ('short_description', 'description', 'cover_image_url'),
        }),
        ('Logistics', {
            'fields': ('turnaround_hours', 'pickup_available',
                       'delivery_available', 'same_day'),
        }),
        ('Marketplace', {
            'fields': ('payment_policy', 'is_active'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Listing')
    def listing_link(self, obj):
        if not obj.listing_id:
            return '—'
        url = f'/admin/marketplace/listing/{obj.listing_id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.listing.title)


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------
@admin.register(LaundryOrder)
class LaundryOrderAdmin(admin.ModelAdmin):
    list_display = (
        'reference_display', 'customer_name', 'organization', 'service',
        'status', 'payment_status', 'total_amount', 'balance_display',
        'source', 'created_at',
    )
    list_filter = ('status', 'payment_status', 'source', 'organization')
    search_fields = ('customer_name', 'customer_phone', 'item_description')
    autocomplete_fields = ['organization', 'listing', 'guest_booking', 'service']
    readonly_fields = ('reference_display', 'balance_display',
                       'created_at', 'updated_at', 'delivered_at')
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Who', {
            'fields': ('organization', 'customer_name', 'customer_phone'),
        }),
        ('What', {
            'fields': ('service', 'listing', 'guest_booking',
                       'item_description', 'quantity', 'unit_price'),
        }),
        ('Logistics', {
            'fields': ('pickup_address', 'delivery_address',
                       'scheduled_pickup', 'scheduled_delivery', 'delivered_at'),
        }),
        ('Status', {
            'fields': ('status', 'source', 'payment_policy', 'payment_status'),
        }),
        ('Money', {
            'fields': ('total_amount', 'amount_paid', 'balance_display'),
        }),
        ('Notes', {
            'fields': ('notes',),
        }),
        ('Timestamps', {
            'fields': ('reference_display', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['mark_received', 'mark_washing', 'mark_ready',
               'mark_out_for_delivery', 'mark_delivered', 'mark_cancelled']

    @admin.display(description='Reference')
    def reference_display(self, obj):
        return obj.reference

    @admin.display(description='Balance')
    def balance_display(self, obj):
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

    @admin.action(description='Mark selected → received')
    def mark_received(self, request, queryset):
        self._bulk_status(request, queryset, 'received')

    @admin.action(description='Mark selected → washing')
    def mark_washing(self, request, queryset):
        self._bulk_status(request, queryset, 'washing')

    @admin.action(description='Mark selected → ready')
    def mark_ready(self, request, queryset):
        self._bulk_status(request, queryset, 'ready')

    @admin.action(description='Mark selected → out for delivery')
    def mark_out_for_delivery(self, request, queryset):
        self._bulk_status(request, queryset, 'out_for_delivery')

    @admin.action(description='Mark selected → delivered')
    def mark_delivered(self, request, queryset):
        self._bulk_status(request, queryset, 'delivered')

    @admin.action(description='Mark selected → cancelled')
    def mark_cancelled(self, request, queryset):
        self._bulk_status(request, queryset, 'cancelled')


# ---------------------------------------------------------------------------
# Supply
# ---------------------------------------------------------------------------
@admin.register(LaundrySupply)
class LaundrySupplyAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'quantity', 'unit',
                    'reorder_level', 'is_low_stock')
    list_filter = ('organization', 'unit')
    search_fields = ('name', 'notes')
    autocomplete_fields = ['organization']

    @admin.display(boolean=True, description='Low stock?')
    def is_low_stock(self, obj):
        return obj.quantity <= obj.reorder_level