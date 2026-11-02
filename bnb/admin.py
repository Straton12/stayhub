# bnb/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Property, Guest, Booking,
    HousekeepingTask, MaintenanceRequest,
    Expense, ExpenseCategory, Revenue,
    Invoice, Payment, StaffMember, Review, ActivityLog,
)


# ============================================================
#  Property
# ============================================================
@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'organization', 'category', 'price', 'price_unit',
        'is_active', 'has_listing_badge', 'created_at',
    )
    list_filter = ('is_active', 'category', 'organization')
    search_fields = ('name', 'location_label', 'address', 'email', 'phone')
    autocomplete_fields = ['organization', 'category']
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at', 'listing_link')

    fieldsets = (
        ('Identity', {
            'fields': ('organization', 'name', 'category',
                       'short_description', 'description'),
        }),
        ('Location', {
            'fields': ('location_label', 'address', 'latitude', 'longitude'),
        }),
        ('Contact', {
            'fields': ('phone', 'email', 'whatsapp'),
        }),
        ('Social links (all optional)', {
            'classes': ('collapse',),
            'fields': ('website', 'facebook', 'instagram',
                       'twitter', 'tiktok', 'youtube'),
        }),
        ('Commercial', {
            'fields': ('price', 'price_unit', 'min_nights', 'max_guests',
                       'bedrooms', 'baths'),
        }),
        ('Check-in / policies', {
            'fields': ('check_in_time', 'check_out_time',
                       'amenities', 'house_rules'),
        }),
        ('Images (max 4)', {
            'fields': ('cover_image', 'image_2', 'image_3', 'image_4'),
        }),
        ('Marketplace', {
            'fields': ('is_active', 'listing_link'),
        }),
        ('Timestamps', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at'),
        }),
    )

    @admin.display(boolean=True, description='On marketplace?')
    def has_listing_badge(self, obj):
        return bool(obj.listing_id)

    @admin.display(description='Marketplace listing')
    def listing_link(self, obj):
        if not obj.listing_id:
            return '—'
        return format_html(
            '<a href="/admin/marketplace/listing/{}/change/">Listing #{}</a>',
            obj.listing_id, obj.listing_id,
        )


# ============================================================
#  Guest
# ============================================================
@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'phone', 'country', 'is_blacklisted')
    list_filter = ('is_blacklisted', 'country')
    search_fields = ('full_name', 'email', 'phone', 'id_number')
    autocomplete_fields = ['organization', 'user']


# ============================================================
#  Booking
# ============================================================
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'guest_name', 'property', 'check_in', 'check_out',
        'status', 'source', 'total_amount', 'amount_paid',
    )
    list_filter = ('status', 'source', 'payment_status')
    search_fields = ('guest_name', 'guest_email', 'guest_phone', 'property__name')
    autocomplete_fields = ['property', 'guest', 'guest_booking']
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at', 'guest_booking')


# ============================================================
#  Housekeeping / Maintenance
# ============================================================
@admin.register(HousekeepingTask)
class HousekeepingTaskAdmin(admin.ModelAdmin):
    list_display = ('description', 'property', 'task_type', 'priority', 'status', 'scheduled_for')
    list_filter = ('status', 'priority', 'task_type')
    search_fields = ('description', 'assigned_to', 'property__name')
    autocomplete_fields = ['property']
    date_hierarchy = 'created_at'


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ('issue', 'property', 'category', 'priority', 'status')
    list_filter = ('status', 'priority', 'category')
    search_fields = ('issue', 'description', 'reported_by', 'property__name')
    autocomplete_fields = ['property']
    date_hierarchy = 'created_at'


# ============================================================
#  Finance
# ============================================================
@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'is_recurring')
    list_filter = ('is_recurring',)
    search_fields = ('name',)
    autocomplete_fields = ['organization']


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'property', 'amount', 'frequency', 'expense_date', 'paid')
    list_filter = ('frequency', 'payment_method', 'paid')
    search_fields = ('title', 'vendor', 'description')
    autocomplete_fields = ['organization', 'property', 'category', 'created_by']
    date_hierarchy = 'expense_date'


@admin.register(Revenue)
class RevenueAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'property', 'source', 'amount', 'revenue_date')
    list_filter = ('source',)
    search_fields = ('title', 'notes')
    autocomplete_fields = ['organization', 'property', 'booking']
    date_hierarchy = 'revenue_date'


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'guest_name', 'total', 'amount_paid', 'status', 'issue_date')
    list_filter = ('status',)
    search_fields = ('invoice_number', 'guest_name', 'guest_email')
    autocomplete_fields = ['organization', 'booking']
    date_hierarchy = 'issue_date'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'organization', 'booking', 'invoice', 'amount', 'method', 'payment_date')
    list_filter = ('method',)
    autocomplete_fields = ['organization', 'booking', 'invoice']
    date_hierarchy = 'payment_date'


# ============================================================
#  Staff / Reviews / Logs
# ============================================================
@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'organization', 'property', 'role', 'is_active')
    list_filter = ('role', 'is_active')
    search_fields = ('full_name', 'email', 'phone')
    autocomplete_fields = ['organization', 'property', 'user']


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('guest_name', 'property', 'rating', 'source', 'review_date')
    list_filter = ('source', 'rating')
    search_fields = ('guest_name', 'comment', 'property__name')
    autocomplete_fields = ['organization', 'property', 'booking']
    date_hierarchy = 'review_date'


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'organization', 'user', 'created_at')
    list_filter = ('organization',)
    search_fields = ('action', 'details')
    autocomplete_fields = ['organization', 'user']
    date_hierarchy = 'created_at'