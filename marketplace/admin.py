# marketplace/admin.py
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Listing, ListingAvailabilityBlock, ListingCategory,
    ListingImage, Review, Wishlist,
)
from .publishing import approve, reject


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------
@admin.register(ListingCategory)
class ListingCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'accent', 'display_order', 'listing_count_display')
    list_editable = ('accent', 'display_order')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'description')

    @admin.display(description='Listings')
    def listing_count_display(self, obj):
        return obj.listings.count()


# ---------------------------------------------------------------------------
# Listing inlines
# ---------------------------------------------------------------------------
class ListingImageInline(admin.TabularInline):
    model = ListingImage
    extra = 1
    fields = ('image', 'image_url', 'caption', 'display_order')


class AvailabilityBlockInline(admin.TabularInline):
    model = ListingAvailabilityBlock
    extra = 0
    fields = ('guest_booking', 'start_date', 'end_date', 'status')
    autocomplete_fields = ['guest_booking']
    show_change_link = True


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'organization', 'category', 'status',
        'price', 'price_unit', 'is_active',
        'has_contact_badge', 'has_socials_badge',
        'approved_at', 'source_link',
    )
    list_filter = (
        'status', 'category', 'is_active', 'organization',
    )
    search_fields = (
        'title', 'short_description', 'description',
        'location', 'address', 'contact_phone', 'contact_email',
    )
    autocomplete_fields = ['organization', 'category', 'approved_by']
    readonly_fields = (
        'view_count', 'booking_count', 'average_rating',
        'review_count', 'wishlist_count',
        'created_at', 'updated_at', 'approved_at', 'source_link',
    )
    inlines = [ListingImageInline, AvailabilityBlockInline]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Identity', {
            'fields': ('title', 'slug', 'organization', 'category', 'source_link'),
        }),
        ('Copy', {
            'fields': ('short_description', 'description',
                       'cover_image', 'cover_image_url'),
        }),
        ('Location', {
            'fields': ('location', 'address', 'latitude', 'longitude'),
        }),
        ('Contact', {
            'fields': ('contact_phone', 'contact_email', 'whatsapp'),
        }),
        ('Social links (all optional)', {
            'classes': ('collapse',),
            'fields': ('website', 'facebook', 'instagram',
                       'twitter', 'tiktok', 'youtube'),
        }),
        ('Commercial', {
            'fields': ('price', 'price_unit', 'min_nights', 'max_guests',
                       'bedrooms', 'beds', 'baths',
                       'payment_policy', 'deposit_percent', 'service_fee_percent'),
        }),
        ('Rules', {
            'fields': ('amenities', 'house_rules',
                       'check_in_time', 'check_out_time', 'cancellation_policy'),
        }),
        ('Moderation', {
            'fields': ('status', 'is_active', 'accepts_bookings', 'pay_first',
                       'rejection_note', 'approved_at', 'approved_by'),
        }),
        ('Stats', {
            'fields': ('view_count', 'booking_count',
                       'average_rating', 'review_count', 'wishlist_count'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'approve_listings', 'reject_listings',
        'unpublish_listings', 'recalculate_ratings',
        'recalculate_wishlist_counts',
    ]

    # ---- Columns ----------------------------------------------------------
    @admin.display(description='Source row')
    def source_link(self, obj):
        if not (obj.source_app and obj.source_model and obj.source_id):
            return '—'
        url = (
            f"/admin/{obj.source_app}/"
            f"{obj.source_model.lower()}/{obj.source_id}/change/"
        )
        return format_html('<a href="{}">{} #{}</a>',
                           url, obj.source_model, obj.source_id)

    @admin.display(boolean=True, description='Contact?')
    def has_contact_badge(self, obj):
        return obj.has_contact

    @admin.display(boolean=True, description='Socials?')
    def has_socials_badge(self, obj):
        return obj.has_social_links

    # ---- Actions ----------------------------------------------------------
    @admin.action(description='Approve selected listings')
    def approve_listings(self, request, queryset):
        for listing in queryset:
            approve(listing, by_user=request.user)
        self.message_user(request, f'{queryset.count()} listing(s) approved.')

    @admin.action(description='Reject selected listings')
    def reject_listings(self, request, queryset):
        for listing in queryset:
            reject(listing, note='Bulk rejection', by_user=request.user)
        self.message_user(request, f'{queryset.count()} listing(s) rejected.')

    @admin.action(description='Unpublish selected listings')
    def unpublish_listings(self, request, queryset):
        n = queryset.update(status='unpublished', is_active=False)
        self.message_user(request, f'{n} listing(s) unpublished.')

    @admin.action(description='Recalculate ratings')
    def recalculate_ratings(self, request, queryset):
        for l in queryset:
            l.recalc_rating()
        self.message_user(request, f'Recalculated {queryset.count()} listing(s).')

    @admin.action(description='Recalculate wishlist counts')
    def recalculate_wishlist_counts(self, request, queryset):
        for l in queryset:
            l.recalc_wishlist_count()
        self.message_user(request, f'Recalculated {queryset.count()} listing(s).')


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'listing', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email', 'listing__title')
    autocomplete_fields = ['user', 'listing']
    date_hierarchy = 'created_at'


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('listing', 'user', 'rating', 'is_published', 'created_at')
    list_filter = ('rating', 'is_published', 'created_at')
    search_fields = ('listing__title', 'user__username', 'title', 'body')
    autocomplete_fields = ['listing', 'user']
    readonly_fields = ('created_at',)
    actions = ['publish_reviews', 'unpublish_reviews']

    @admin.action(description='Publish selected reviews')
    def publish_reviews(self, request, queryset):
        n = queryset.update(is_published=True)
        for r in queryset:
            r.listing.recalc_rating()
        self.message_user(request, f'{n} review(s) published.')

    @admin.action(description='Unpublish selected reviews')
    def unpublish_reviews(self, request, queryset):
        n = queryset.update(is_published=False)
        for r in queryset:
            r.listing.recalc_rating()
        self.message_user(request, f'{n} review(s) unpublished.')


# ---------------------------------------------------------------------------
# Availability blocks
# ---------------------------------------------------------------------------
@admin.register(ListingAvailabilityBlock)
class ListingAvailabilityBlockAdmin(admin.ModelAdmin):
    list_display = (
        'listing', 'guest_booking', 'start_date', 'end_date',
        'status', 'is_expired',
    )
    list_filter = ('status', 'start_date')
    search_fields = ('listing__title',)
    autocomplete_fields = ['listing', 'guest_booking']
    date_hierarchy = 'start_date'
    actions = ['release_blocks', 'release_expired']

    @admin.action(description='Release selected availability blocks')
    def release_blocks(self, request, queryset):
        n = queryset.update(status='released')
        self.message_user(request, f'{n} block(s) released.')

    @admin.action(description='Release all expired blocks (end_date < today)')
    def release_expired(self, request, queryset):
        today = timezone.now().date()
        n = queryset.filter(
            status__in=['pending', 'confirmed'],
            end_date__lte=today,
        ).update(status='released')
        self.message_user(request, f'{n} expired block(s) released.')