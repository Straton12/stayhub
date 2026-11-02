# guestaccount/urls.py
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = 'guestaccount'

urlpatterns = [
    # =========================================================================
    # GUEST HOME  — "My bookings"
    # =========================================================================
    path('', views.home, name='home'),

    # =========================================================================
    # BOOKING FLOW
    # =========================================================================
    # Create a new booking for a listing
    path(
        'book/<slug:listing_slug>/',
        views.booking_new,
        name='booking_new',
    ),

    # View a booking
    path(
        'booking/<int:pk>/',
        views.booking_detail,
        name='booking_detail',
    ),

    # Confirm & pay (routes to payments:initiate for pay-now flows)
    path(
        'booking/<int:pk>/confirm/',
        views.booking_confirm,
        name='booking_confirm',
    ),

    # Cancel
    path(
        'booking/<int:pk>/cancel/',
        views.booking_cancel,
        name='booking_cancel',
    ),

    # Leave a 5-star review  (NEW — only for completed / in-progress bookings)
    path(
        'booking/<int:pk>/review/',
        views.booking_review,
        name='booking_review',
    ),

    # Status change — callable by the guest OR the owning org
    path(
        'booking/<int:pk>/status/<str:new_status>/',
        views.booking_status_update,
        name='booking_status',
    ),

    # =========================================================================
    # RECEIPTS
    # =========================================================================
    path('receipts/', views.receipt_list, name='receipt_list'),

    # =========================================================================
    # PROFILE
    # =========================================================================
    path('profile/', views.profile, name='profile'),

    # =========================================================================
    # PASSWORD CHANGE  (Django built-ins, guest-styled templates)
    # =========================================================================
    path(
        'password/change/',
        auth_views.PasswordChangeView.as_view(
            template_name='guestaccount/password_change.html',
            success_url=reverse_lazy('guestaccount:password_change_done'),
        ),
        name='password_change',
    ),
    path(
        'password/change/done/',
        auth_views.PasswordChangeDoneView.as_view(
            template_name='guestaccount/password_change_done.html',
        ),
        name='password_change_done',
    ),
]