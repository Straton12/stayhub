# notifications/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from .models import NotificationLog
from .services import retry_notification


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'channel', 'status', 'priority', 'kind', 'event',
        'recipient_display', 'subject', 'is_read_display',
    )
    list_filter = ('channel', 'status', 'priority', 'kind', 'event')
    search_fields = ('to_email', 'to_phone', 'subject', 'body',
                     'related_object_repr', 'event', 'kind')
    readonly_fields = ('created_at', 'sent_at', 'read_at',
                       'error', 'retry_count',
                       'recipient_user', 'recipient_organization',
                       'guest_booking')
    date_hierarchy = 'created_at'
    autocomplete_fields = ['recipient_user', 'recipient_organization', 'guest_booking']

    fieldsets = (
        ('Recipient', {
            'fields': ('recipient_user', 'recipient_organization',
                       'to_email', 'to_phone'),
        }),
        ('Content', {
            'fields': ('subject', 'body'),
        }),
        ('Event', {
            'fields': ('channel', 'status', 'priority',
                       'event', 'kind', 'related_object_repr'),
        }),
        ('Links', {
            'fields': ('guest_booking',),
        }),
        ('Timestamps & errors', {
            'fields': ('created_at', 'sent_at', 'read_at',
                       'error', 'retry_count'),
            'classes': ('collapse',),
        }),
    )

    actions = ['resend_selected', 'mark_as_read', 'mark_as_failed']

    @admin.display(description='Recipient')
    def recipient_display(self, obj):
        if obj.recipient_user:
            return obj.recipient_user
        if obj.recipient_organization:
            return obj.recipient_organization
        return obj.to_email or obj.to_phone or '—'

    @admin.display(boolean=True, description='Read')
    def is_read_display(self, obj):
        return obj.read_at is not None

    @admin.action(description='Resend selected (email/SMS only)')
    def resend_selected(self, request, queryset):
        n = 0
        for log in queryset:
            if log.channel in ('email', 'sms'):
                try:
                    retry_notification(log.id)
                    n += 1
                except Exception:
                    pass
        self.message_user(request, f'{n} notification(s) resent.')

    @admin.action(description='Mark selected as read')
    def mark_as_read(self, request, queryset):
        now = timezone.now()
        n = queryset.filter(read_at__isnull=True).update(
            read_at=now, status='read',
        )
        self.message_user(request, f'{n} notification(s) marked as read.')

    @admin.action(description='Mark selected as failed')
    def mark_as_failed(self, request, queryset):
        n = queryset.update(status='failed')
        self.message_user(request, f'{n} notification(s) marked failed.')