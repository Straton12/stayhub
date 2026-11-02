# marketplace/urls.py
from django.urls import path

from . import views

app_name = 'marketplace'

urlpatterns = [
    # ===========================================================================
    # PUBLIC  — browsable by anyone (guest, staff, anonymous)
    # ===========================================================================
    path('',                              views.home,          name='home'),
    path('search/',                       views.search,        name='search'),
    path('browse/<slug:slug>/',           views.category_page, name='category'),

    # ===========================================================================
    # LISTING DETAIL + GUEST ACTIONS
    # ===========================================================================
    # Anyone can view; only guests can book / save / review.
    path(
        'listing/<slug:slug>/',
        views.listing_detail,
        name='listing_detail',
    ),
    path(
        'listing/<slug:slug>/book/',
        views.book_start,
        name='book_start',
    ),
    # Wishlist toggle — counter + org notification handled by
    # marketplace/signals.py (post_save / post_delete on Wishlist).
    path(
        'listing/<slug:slug>/wishlist/',
        views.wishlist_toggle,
        name='wishlist_toggle',
    ),
    # Review submit — rating aggregate + org notification handled by
    # marketplace/signals.py (post_save on Review).
    path(
        'listing/<slug:slug>/review/',
        views.review_submit,
        name='review_submit',
    ),

    # Guest's own saved listings
    path(
        'my/wishlist/',
        views.wishlist_list,
        name='wishlist',
    ),

    # ===========================================================================
    # ORG-ADMIN  — category management
    # ===========================================================================
    path(
        'manage/categories/',
        views.manage_categories,
        name='manage_categories',
    ),
    path(
        'manage/categories/new/',
        views.manage_category_create,
        name='manage_category_create',
    ),
    path(
        'manage/categories/<int:pk>/edit/',
        views.manage_category_edit,
        name='manage_category_edit',
    ),
    path(
        'manage/categories/<int:pk>/delete/',
        views.manage_category_delete,
        name='manage_category_delete',
    ),

    # ===========================================================================
    # ORG-ADMIN  — listing management
    # ===========================================================================
    # IMPORTANT: The exact `manage/` paths come BEFORE `<int:pk>` paths.
    # Django tries patterns top-to-bottom, so `manage/new/` must precede
    # `manage/<int:pk>/edit/` to avoid ever accidentally matching `new`
    # as a pk in a future refactor that loosens the pattern.
    path(
        'manage/',
        views.manage_home,
        name='manage_home',
    ),
    path(
        'manage/new/',
        views.manage_create,
        name='manage_create',
    ),
    path(
        'manage/<int:pk>/edit/',
        views.manage_edit,
        name='manage_edit',
    ),
    path(
        'manage/<int:pk>/delete/',
        views.manage_delete,
        name='manage_delete',
    ),
    path(
        'manage/<int:pk>/toggle/',
        views.manage_toggle,
        name='manage_toggle',
    ),

    # ===========================================================================
    # SUPERADMIN  — moderation queue
    # ===========================================================================
    path(
        'moderation/',
        views.moderation_queue,
        name='moderation_queue',
    ),
    path(
        'moderation/<int:pk>/approve/',
        views.moderation_approve,
        name='moderation_approve',
    ),
    path(
        'moderation/<int:pk>/reject/',
        views.moderation_reject,
        name='moderation_reject',
    ),
]