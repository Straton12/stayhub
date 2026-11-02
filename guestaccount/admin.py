# guestaccount/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import GuestProfile, GuestBooking


# ---------------------------------------------------------------------------
# GuestProfile
# ---------------------------------------------------------------------------
@admin.register(GuestProfile)
class GuestProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'country', 'city', 'marketing_opt_in', 'created_at')
    search_fields = ('user__username', 'user__email', 'user__full_name')
    list_filter = ('country', 'marketing_opt_in')
    autocomplete_fields = ['user']
    readonly_fields = ('created_at', 'updated_at')


# ---------------------------------------------------------------------------
# GuestBooking
# ---------------------------------------------------------------------------
class PaymentAttemptInline(admin.TabularInline):
    model = None  # set below to avoid import order issues
    extra = 0
    fields = ('reference', 'method', 'amount', 'status', 'created_at')
    readonly_fields = ('reference', 'method', 'amount', 'status', 'created_at')
    show_change_link = True
    can_delete = False

    def get_queryset(self, request):
        return super().get_queryset(request)


# Attach the actual model after imports
try:
    from payments.models import PaymentAttempt, Receipt
    PaymentAttemptInline.model = PaymentAttempt

    class ReceiptInline(admin.TabularInline):
        model = Receipt
        extra = 0
        fields = ('number', 'amount', 'currency', 'issued_at')
        readonly_fields = ('number', 'amount', 'currency', 'issued_at')
        show_change_link = True
        can_delete = False
except Exception:
    ReceiptInline = None


@admin.register(GuestBooking)
class GuestBookingAdmin(admin.ModelAdmin):
    list_display = (
        'reference_display', 'customer_name', 'listing', 'organization',
        'kind', 'status', 'total_amount', 'amount_paid_display',
        'source_link', 'created_at',
    )
    list_filter = ('status', 'kind', 'organization', 'listing__category')
    search_fields = (
        'customer_name', 'customer_email', 'customer_phone',
        'payment_reference', 'pk',
    )
    readonly_fields = (
        'reference_display', 'created_at', 'updated_at', 'paid_at',
        'source_link', 'balance_display',
    )
    autocomplete_fields = ['user', 'listing', 'organization']
    date_hierarchy = 'created_at'
    inlines = [PaymentAttemptInline] + ([ReceiptInline] if ReceiptInline else [])

    fieldsets = (
        ('Identity', {
            'fields': ('reference_display', 'user', 'kind', 'status'),
        }),
        ('What', {
            'fields': ('listing', 'organization', 'source_link'),
        }),
        ('Customer', {
            'fields': ('customer_name', 'customer_email', 'customer_phone'),
        }),
        ('Dates', {
            'fields': ('start_date', 'end_date'),
        }),
        ('Money', {
            'fields': (
                'currency', 'unit_price', 'quantity', 'subtotal',
                'service_fee', 'total_amount', 'amount_paid',
                'balance_display', 'payment_policy', 'payment_reference',
                'paid_at',
            ),
        }),
        ('Details', {
            'fields': ('details', 'guest_note', 'org_note'),
        }),
        ('Acknowledgment', {
            'fields': ('is_acknowledged', 'acknowledged_at'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['mark_confirmed', 'mark_in_progress', 'mark_completed',
               'mark_cancelled', 'acknowledge']

    @admin.display(description='Reference')
    def reference_display(self, obj):
        return obj.reference

    @admin.display(description='Balance')
    def balance_display(self, obj):
        return obj.balance

    @admin.display(description='Amount paid')
    def amount_paid_display(self, obj):
        return f"{obj.amount_paid} {obj.currency}"

    @admin.display(description='Source row')
    def source_link(self, obj):
        if not (obj.source_app and obj.source_model and obj.source_id):
            return '—'
        url = f"/admin/{obj.source_app}/{obj.source_model.lower()}/{obj.source_id}/change/"
        return format_html('<a href="{}">{} #{}</a>',
                           url, obj.source_model, obj.source_id)

    @admin.action(description='Mark selected bookings confirmed')
    def mark_confirmed(self, request, queryset):
        for b in queryset:
            try:
                b.mark_confirmed()
            except Exception:
                pass
        self.message_user(request, f'{queryset.count()} booking(s) confirmed.')

    @admin.action(description='Mark selected bookings in progress')
    def mark_in_progress(self, request, queryset):
        for b in queryset:
            try:
                b.mark_in_progress()
            except Exception:
                pass
        self.message_user(request, f'{queryset.count()} booking(s) in progress.')

    @admin.action(description='Mark selected bookings completed')
    def mark_completed(self, request, queryset):
        for b in queryset:
            try:
                b.mark_completed()
            except Exception:
                pass
        self.message_user(request, f'{queryset.count()} booking(s) completed.')

    @admin.action(description='Mark selected bookings cancelled')
    def mark_cancelled(self, request, queryset):
        for b in queryset:
            try:
                b.mark_cancelled()
            except Exception:
                pass
        self.message_user(request, f'{queryset.count()} booking(s) cancelled.')

    @admin.action(description='Acknowledge selected bookings')
    def acknowledge(self, request, queryset):
        for b in queryset:
            try:
                b.acknowledge()
            except Exception:
                pass
        self.message_user(request, f'{queryset.count()} booking(s) acknowledged.')