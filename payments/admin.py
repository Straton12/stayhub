# payments/admin.py
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from . import services
from .models import PaymentAttempt, Receipt


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'guest_booking_link', 'method', 'status',
        'amount', 'currency', 'mpesa_receipt', 'is_deposit',
        'created_at', 'completed_at',
    )
    list_filter = ('method', 'status', 'currency', 'is_deposit', 'policy')
    search_fields = ('reference', 'guest_booking__customer_name',
                     'guest_booking__customer_phone',
                     'mpesa_checkout_request_id', 'mpesa_receipt')
    autocomplete_fields = ['guest_booking', 'user', 'recorded_by']
    readonly_fields = ('reference', 'created_at', 'updated_at',
                       'completed_at', 'paid_in_full_at', 'provider_payload')
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Identity', {
            'fields': ('reference', 'guest_booking', 'user', 'recorded_by'),
        }),
        ('Money', {
            'fields': ('amount', 'currency', 'is_deposit',
                       'deposit_percent', 'policy'),
        }),
        ('Method & status', {
            'fields': ('method', 'status'),
        }),
        ('M-Pesa', {
            'fields': ('mpesa_phone', 'mpesa_checkout_request_id',
                       'mpesa_merchant_request_id', 'mpesa_receipt',
                       'mpesa_result_code', 'mpesa_result_description'),
        }),
        ('Provider payload', {
            'fields': ('provider_payload',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at',
                       'paid_in_full_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['mark_succeeded', 'mark_failed', 'refund_selected']

    @admin.display(description='GuestBooking')
    def guest_booking_link(self, obj):
        if not obj.guest_booking_id:
            return '—'
        url = f'/admin/guestaccount/guestbooking/{obj.guest_booking_id}/change/'
        return format_html('<a href="{}">#{}</a>', url, obj.guest_booking_id)

    @admin.action(description='Mark selected attempts as succeeded')
    def mark_succeeded(self, request, queryset):
        n = 0
        for a in queryset:
            if a.status in ('pending', 'processing'):
                try:
                    services.complete_attempt(a)
                    n += 1
                except Exception:
                    pass
        self.message_user(request, f'{n} attempt(s) completed.')

    @admin.action(description='Mark selected attempts as failed')
    def mark_failed(self, request, queryset):
        n = 0
        for a in queryset.exclude(status='succeeded'):
            try:
                services.fail_attempt(a, reason='Admin action')
                n += 1
            except Exception:
                pass
        self.message_user(request, f'{n} attempt(s) failed.')

    @admin.action(description='Refund selected succeeded attempts')
    def refund_selected(self, request, queryset):
        n = 0
        for a in queryset.filter(status='succeeded'):
            try:
                services.refund_attempt(a, note='Admin refund')
                n += 1
            except Exception:
                pass
        self.message_user(request, f'{n} attempt(s) refunded.')


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('number', 'guest_booking_link', 'amount', 'currency',
                    'business_name', 'customer_name', 'issued_at')
    list_filter = ('currency',)
    search_fields = ('number', 'guest_booking__customer_name',
                     'guest_booking__customer_phone')
    autocomplete_fields = ['guest_booking', 'payment_attempt']
    readonly_fields = ('number', 'issued_at')
    date_hierarchy = 'issued_at'

    @admin.display(description='GuestBooking')
    def guest_booking_link(self, obj):
        if not obj.guest_booking_id:
            return '—'
        url = f'/admin/guestaccount/guestbooking/{obj.guest_booking_id}/change/'
        return format_html('<a href="{}">#{}</a>', url, obj.guest_booking_id)