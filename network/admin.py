# network/admin.py

from django.contrib import admin
from django.utils.html import format_html

from .models import NetworkFavorite, NetworkProfile, Referral


# ---------------------------------------------------------------------------
# Referral
# ---------------------------------------------------------------------------
@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = (
        'reference_display',
        'from_org', 'to_org',
        'guest_name',
        'service_needed',
        'status_badge',          # NEW — colour-coded status
        'match_reason',
        'is_auto',
        'value_display',
        'commission_display',
        'commission_paid',
        'source',
        'created_at',
    )
    list_filter = (
        'status',
        'is_auto',
        'match_reason',
        'source',
        'commission_paid',
        'from_org',
        'to_org',
    )
    search_fields = (
        'guest_name', 'guest_phone', 'guest_email',
        'service_needed',
        'from_org__name', 'to_org__name',
    )
    autocomplete_fields = ['from_org', 'to_org', 'guest_booking']
    readonly_fields = (
        'reference_display',
        'created_at',
        'accepted_at',
        'completed_at',
        'commission_paid_at',
    )
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Parties', {
            'fields': ('from_org', 'to_org', 'guest_booking'),
        }),
        ('Guest', {
            'fields': ('guest_name', 'guest_phone', 'guest_email'),
        }),
        ('Service', {
            'fields': ('service_needed', 'notes', 'source'),
        }),
        ('Status', {
            'fields': ('status', 'accepted_at', 'completed_at'),
        }),
        ('Commission', {
            'fields': (
                'value', 'commission', 'commission_rate',
                'referrer_payout',
                'commission_paid', 'commission_paid_at',
            ),
        }),
        ('Auto overflow', {
            'fields': ('is_auto', 'match_reason'),
            'classes': ('collapse',),
        }),
        ('Meta', {
            'fields': ('reference_display', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['mark_accepted', 'mark_completed', 'mark_rejected', 'mark_paid']

    # ------------------------------------------------------------------
    # Display columns
    # ------------------------------------------------------------------
    @admin.display(description='Reference', ordering='-created_at')
    def reference_display(self, obj):
        return obj.reference

    @admin.display(description='Status', ordering='status')
    def status_badge(self, obj):
        colors = {
            'auto_pending': '#f59e0b',
            'pending':      '#f59e0b',
            'accepted':     '#22d3ee',
            'completed':    '#10b981',
            'rejected':     '#ef4444',
            'expired':      '#94a3b8',
            'no_match':     '#dc2626',
        }
        color = colors.get(obj.status, '#64748b')
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;'
            'border-radius:999px;font-size:11px;font-weight:700;'
            'color:#fff;background:{};">{}</span>',
            color, obj.get_status_display(),
        )

    @admin.display(description='Value (KES)', ordering='value')
    def value_display(self, obj):
        return f'KES {obj.value:,.0f}'

    @admin.display(description='Commission', ordering='commission')
    def commission_display(self, obj):
        if obj.commission_paid:
            return format_html(
                '<span style="color:#047857;font-weight:700;">'
                'KES {} ✓</span>',
                f'{obj.commission:,.0f}',
            )
        return format_html(
            '<span style="color:#b45309;font-weight:700;">'
            'KES {}</span>',
            f'{obj.commission:,.0f}',
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    @admin.action(description='Mark selected referrals accepted')
    def mark_accepted(self, request, queryset):
        ok = 0
        for r in queryset:
            try:
                r.mark_accepted()
                ok += 1
            except Exception:
                pass
        self.message_user(request, f'{ok} referral(s) accepted.')

    @admin.action(description='Mark selected referrals completed')
    def mark_completed(self, request, queryset):
        ok = 0
        for r in queryset:
            try:
                r.mark_completed()
                ok += 1
            except Exception:
                pass
        self.message_user(request, f'{ok} referral(s) completed.')

    @admin.action(description='Mark selected referrals rejected')
    def mark_rejected(self, request, queryset):
        ok = 0
        for r in queryset:
            try:
                r.mark_rejected()
                ok += 1
            except Exception:
                pass
        self.message_user(request, f'{ok} referral(s) rejected.')

    @admin.action(description='Mark selected commissions paid')
    def mark_paid(self, request, queryset):
        ok = 0
        for r in queryset:
            try:
                r.mark_paid()
                ok += 1
            except Exception:
                pass
        self.message_user(request, f'{ok} commission(s) marked paid.')


# ---------------------------------------------------------------------------
# NetworkFavorite
# ---------------------------------------------------------------------------
@admin.register(NetworkFavorite)
class NetworkFavoriteAdmin(admin.ModelAdmin):
    list_display = ('organization', 'listing', 'priority', 'created_at')
    list_filter = ('organization',)
    search_fields = ('organization__name', 'listing__title')
    autocomplete_fields = ['organization', 'listing']
    readonly_fields = ('created_at',)


# ---------------------------------------------------------------------------
# NetworkProfile
# ---------------------------------------------------------------------------
@admin.register(NetworkProfile)
class NetworkProfileAdmin(admin.ModelAdmin):
    list_display = (
        'organization', 'tagline', 'service_area',
        'offers_referrals', 'accepts_referrals', 'visible_to_guests',
        'commission_rate', 'created_at',
    )
    list_filter = (
        'offers_referrals', 'accepts_referrals', 'visible_to_guests',
    )
    search_fields = ('organization__name', 'tagline', 'service_area')
    autocomplete_fields = ['organization']
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Organization', {
            'fields': ('organization',),
        }),
        ('Copy', {
            'fields': ('tagline', 'service_area', 'categories'),
        }),
        ('Preferences', {
            'fields': (
                'offers_referrals', 'accepts_referrals',
                'visible_to_guests', 'commission_rate',
            ),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )