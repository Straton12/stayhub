# guestaccount/middleware.py
from .models import GuestProfile


class GuestProfileMiddleware:
    """
    Attaches `request.guest_profile` to every request.

    For guests (role='guest'), it auto-creates a GuestProfile on
    first login. Org admins / superadmins / anonymous users get
    `None`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.guest_profile = None

        user = getattr(request, 'user', None)
        if (
            user
            and user.is_authenticated
            and getattr(user, 'is_guest', False)
            and not getattr(user, 'is_superadmin', False)
            and not getattr(user, 'is_orgadmin', False)
        ):
            try:
                profile, _ = GuestProfile.objects.get_or_create(user=user)
                request.guest_profile = profile
            except Exception:
                request.guest_profile = None

        return self.get_response(request)