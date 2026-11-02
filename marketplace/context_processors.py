# marketplace/context_processors.py
from .models import ListingCategory, Wishlist


def marketplace_context(request):
    try:
        categories = list(
            ListingCategory.objects.all().order_by('display_order', 'name')
        )
    except Exception:
        categories = []

    wishlist_count = 0
    user = getattr(request, 'user', None)
    if user and user.is_authenticated and getattr(user, 'is_guest', False):
        try:
            wishlist_count = Wishlist.objects.filter(user=user).count()
        except Exception:
            wishlist_count = 0

    return {
        'marketplace_categories': categories,
        'wishlist_count': wishlist_count,
    }