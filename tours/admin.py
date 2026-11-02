# tours/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import Guide, TourBooking, TourPackage, Vehicle


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------
class TourBookingInline(admin.TabularInline):
    model = TourBooking
    extra = 0
    fields = ('customer_name', 'travel_date', 'travellers_count',
              'status', 'payment_status', 'total_amount', 'amount_paid')
    show_change_link = True


# ---------------------------------------------------------------------------
# TourPackage
# ---------------------------------------------------------------------------
@admin.register(TourPackage)
class TourPackageAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'organization', 'package_type', 'destination',
        'duration_days', 'price_per_person', 'is_active', 'listing_link',
    )
    list_filter = ('organization', 'package_type', 'is_active',
                   'pickup_available', 'payment_policy')
    search_fields = ('name', 'destination', 'description')
    autocomplete_fields = ['organization', 'listing']
    readonly_fields = ('created_at', 'updated_at')
    inlines = [TourBookingInline]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Identity', {
            'fields': ('organization', 'name', 'package_type',
                       'destination', 'duration_days', 'listing'),
        }),
        ('Pricing', {
            'fields': ('price_per_person', 'payment_policy',
                       'deposit_percent', 'service_fee_percent'),
        }),
        ('Content', {
            'fields': ('short_description', 'description', 'cover_image_url',
                       'highlights', 'what_to_bring', 'languages'),
        }),
        ('Logistics', {
            'fields': ('min_travellers', 'max_travellers',
                       'pickup_available', 'is_active'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['make_active', 'make_inactive']

    @admin.display(description='Listing')
    def listing_link(self, obj):
        if not obj.listing_id:
            return '—'
        url = f'/admin/marketplace/listing/{obj.listing_id}/change/'
        return format_html('<a href="{}">{}</a>', url, obj.listing.title)

    @admin.action(description='Mark selected packages active')
    def make_active(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f'{n} package(s) activated.')

    @admin.action(description='Mark selected packages inactive')
    def make_inactive(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f'{n} package(s) deactivated.')


# ---------------------------------------------------------------------------
# TourBooking
# ---------------------------------------------------------------------------
@admin.register(TourBooking)
class TourBookingAdmin(admin.ModelAdmin):
    list_display = (
        'reference_display', 'customer_name', 'package',
        'travel_date', 'travellers_count', 'status',
        'payment_status', 'total_amount', 'balance_display', 'source',
    )
    list_filter = ('status', 'payment_status', 'source',
                   'package__organization')
    search_fields = ('customer_name', 'customer_email', 'customer_phone')
    autocomplete_fields = ['package', 'guest_booking']
    readonly_fields = ('reference_display', 'balance_display',
                       'created_at', 'updated_at')
    date_hierarchy = 'travel_date'

    fieldsets = (
        ('Identity', {
            'fields': ('package', 'guest_booking',
                       'customer_name', 'customer_email', 'customer_phone'),
        }),
        ('Trip', {
            'fields': ('travel_date', 'travellers_count',
                       'notes', 'special_requests'),
        }),
        ('Status', {
            'fields': ('status', 'source', 'payment_status'),
        }),
        ('Money', {
            'fields': ('total_amount', 'amount_paid', 'balance_display'),
        }),
        ('Timestamps', {
            'fields': ('reference_display', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['mark_confirmed', 'mark_completed', 'mark_cancelled']

    @admin.display(description='Reference')
    def reference_display(self, obj):
        return obj.reference

    @admin.display(description='Balance')
    def balance_display(self, obj):
        return obj.balance

    def _bulk_status(self, request, queryset, status):
        n = 0
        for b in queryset:
            try:
                b.mark_status(status)
                n += 1
            except Exception:
                pass
        self.message_user(request, f'{n} booking(s) marked {status}.')

    @admin.action(description='Mark selected → confirmed')
    def mark_confirmed(self, request, queryset):
        self._bulk_status(request, queryset, 'confirmed')

    @admin.action(description='Mark selected → completed')
    def mark_completed(self, request, queryset):
        self._bulk_status(request, queryset, 'completed')

    @admin.action(description='Mark selected → cancelled')
    def mark_cancelled(self, request, queryset):
        self._bulk_status(request, queryset, 'cancelled')


# ---------------------------------------------------------------------------
# Guide
# ---------------------------------------------------------------------------
@admin.register(Guide)
class GuideAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'phone', 'languages',
                    'license_number', 'is_active')
    list_filter = ('organization', 'is_active')
    search_fields = ('name', 'phone', 'email', 'languages', 'license_number')
    autocomplete_fields = ['organization']
    readonly_fields = ('created_at',)


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------
@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'plate_number', 'capacity',
                    'vehicle_type', 'is_active')
    list_filter = ('organization', 'is_active', 'vehicle_type')
    search_fields = ('name', 'plate_number', 'vehicle_type')
    autocomplete_fields = ['organization']
    readonly_fields = ('created_at',)