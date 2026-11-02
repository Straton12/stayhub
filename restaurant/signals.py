# restaurant/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import RestaurantProfile

@receiver(post_save, sender=RestaurantProfile)
def sync_restaurant_to_marketplace(sender, instance, created, **kwargs):
    """
    Automatically creates or updates the marketplace Listing
    whenever a RestaurantProfile is saved.
    """
    try:
        from marketplace.models import Listing, ListingCategory, ListingImage
    except Exception:
        # Marketplace app not installed — skip silently
        return

    profile = instance

    # 1. Get or create the 'Food' category
    food_cat, _ = ListingCategory.objects.get_or_create(
        slug='food',
        defaults={
            'name': 'Food & Dining',
            'icon': 'utensils',
            'accent': 'amber',
            'display_order': 20,
        }
    )

    # 2. Decide the status
    if not profile.publish_to_marketplace:
        desired_status = 'unpublished'
        is_active = False
    else:
        desired_status = 'approved'
        is_active = True

    # 3. Build the Listing defaults
    defaults = {
        'organization': profile.organization,
        'category': food_cat,
        'source_app': 'restaurant',
        'source_model': 'RestaurantProfile',
        'source_id': profile.id,
        
        # Copy content
        'title': profile.name,
        'short_description': profile.short_description or (profile.description or '')[:280],
        'description': profile.description or '',
        'cover_image': profile.cover_image or None,
        
        # Location & Contact
        'location': profile.location_label or profile.city or '',
        'address': profile.address or '',
        'latitude': profile.latitude,
        'longitude': profile.longitude,
        'contact_phone': profile.phone or getattr(profile.organization, 'phone', '') or '',
        'contact_email': profile.email or getattr(profile.organization, 'email', '') or '',
        'whatsapp': profile.whatsapp or '',
        
        # Socials
        'website': profile.website or '',
        'facebook': profile.facebook or '',
        'instagram': profile.instagram or '',
        'twitter': profile.twitter or '',
        'tiktok': profile.tiktok or '',
        'youtube': profile.youtube or '',

        # Payment Rules
        'payment_policy': profile.payment_policy,
        'deposit_percent': profile.deposit_percent,
        'service_fee_percent': profile.service_fee_percent or 0,
        'cancellation_policy': profile.cancellation_policy,
        'house_rules': profile.house_rules or '',

        # Marketplace visibility
        'status': desired_status,
        'is_active': is_active,
        'accepts_bookings': is_active and profile.is_open_now,
        
        # Price setup (food doesn't have a single price, it has a menu)
        'price': 0,
        'price_unit': 'menu',
    }

    # 4. Create or update the listing
    listing, _created = Listing.objects.update_or_create(
        source_app='restaurant',
        source_model='RestaurantProfile',
        source_id=profile.id,
        defaults=defaults,
    )

    # 5. Link the listing back to the profile
    if profile.listing_id != listing.id:
        # Use update to avoid recursive signal calls
        RestaurantProfile.objects.filter(pk=profile.pk).update(listing=listing)

    # 6. Sync gallery images (up to 4)
    ListingImage.objects.filter(listing=listing).delete()
    for i, url in enumerate(profile.gallery_image_urls):
        ListingImage.objects.create(
            listing=listing,
            image_url=url,
            display_order=i * 10,
            caption=f"{profile.name} — image {i + 1}",
        )