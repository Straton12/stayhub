# marketplace/signals.py
"""
Marketplace signals.

  • Wishlist add/remove → notify org + refresh Listing.wishlist_count
  • Review create/delete → notify org + refresh Listing.average_rating/review_count
"""

from django.db.models import Avg
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

from .models import Listing, Review, Wishlist


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
@receiver(post_save, sender=Wishlist)
def wishlist_saved(sender, instance, created, **kwargs):
    listing = instance.listing

    # Keep denormalised counter correct
    new_count = Wishlist.objects.filter(listing=listing).count()
    Listing.objects.filter(pk=listing.pk).update(
        wishlist_count=new_count,
        updated_at=timezone.now(),
    )

    # Notify the org only when the like is NEW
    if not created:
        return

    try:
        from notifications.models import NotificationLog
        NotificationLog.objects.create(
            channel='inapp',
            status='sent',
            priority='low',
            kind='listing',
            event='marketplace.wishlist.added',
            recipient_organization=listing.organization,
            subject=f"❤️ {listing.title} was saved",
            body=(
                f"A guest saved your listing. "
                f"It now has {new_count} save{'s' if new_count != 1 else ''}."
            ),
            related_object_repr=str(listing),
        )
    except Exception:
        pass


@receiver(post_delete, sender=Wishlist)
def wishlist_removed(sender, instance, **kwargs):
    listing_id = instance.listing_id
    listing = Listing.objects.filter(pk=listing_id).first()
    if not listing:
        return
    new_count = Wishlist.objects.filter(listing=listing).count()
    Listing.objects.filter(pk=listing.pk).update(
        wishlist_count=new_count,
        updated_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
@receiver(post_save, sender=Review)
def review_saved(sender, instance, created, **kwargs):
    listing = instance.listing

    published = listing.reviews.filter(is_published=True)
    agg = published.aggregate(avg=Avg('rating'))
    Listing.objects.filter(pk=listing.pk).update(
        average_rating=round(agg['avg'] or 0, 2),
        review_count=published.count(),
        updated_at=timezone.now(),
    )

    if not created:
        return

    try:
        from notifications.models import NotificationLog
        NotificationLog.objects.create(
            channel='inapp',
            status='sent',
            priority='normal',
            kind='listing',
            event='marketplace.review.created',
            recipient_organization=listing.organization,
            subject=f"New review ({instance.rating}★) for {listing.title}",
            body=instance.body or '(no comment)',
            related_object_repr=str(instance),
        )
    except Exception:
        pass


@receiver(post_delete, sender=Review)
def review_deleted(sender, instance, **kwargs):
    listing_id = instance.listing_id
    listing = Listing.objects.filter(pk=listing_id).first()
    if not listing:
        return
    published = listing.reviews.filter(is_published=True)
    agg = published.aggregate(avg=Avg('rating'))
    Listing.objects.filter(pk=listing.pk).update(
        average_rating=round(agg['avg'] or 0, 2),
        review_count=published.count(),
        updated_at=timezone.now(),
    )