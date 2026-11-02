# accounts/urls.py
from django.urls import path

from . import views

#app_name = 'accounts'   # optional; keeps reverse() unambiguous

urlpatterns = [
    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    path('login/',    views.login_view,    name='login'),
    path('logout/',   views.logout_view,   name='logout'),
    path('register/', views.guest_register, name='guest_register'),

    # ------------------------------------------------------------------
    # Landing
    # ------------------------------------------------------------------
    path('dashboard/', views.dashboard, name='dashboard'),

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------
    path('password-reset/',
         views.StayHubPasswordResetView.as_view(),
         name='password_reset'),
    path('password-reset/done/',
         views.StayHubPasswordResetDoneView.as_view(),
         name='password_reset_done'),
    path('password-reset/confirm/<uidb64>/<token>/',
         views.StayHubPasswordResetConfirmView.as_view(),
         name='password_reset_confirm'),
    path('password-reset/complete/',
         views.StayHubPasswordResetCompleteView.as_view(),
         name='password_reset_complete'),

    # ------------------------------------------------------------------
    # Super admin — organizations
    # ------------------------------------------------------------------
    path('superadmin/orgs/',
         views.superadmin_orgs, name='superadmin_orgs'),
    path('superadmin/orgs/create/',
         views.superadmin_create_org, name='superadmin_create_org'),
    path('superadmin/orgs/<int:org_id>/',
         views.superadmin_org_detail, name='superadmin_org_detail'),
    path('superadmin/orgs/<int:org_id>/toggle/',
         views.superadmin_toggle_org, name='superadmin_toggle_org'),

    # ------------------------------------------------------------------
    # Org admin — staff management
    # ------------------------------------------------------------------
    path('org/staff/',
         views.org_staff_list, name='org_staff_list'),
    path('org/staff/create/',
         views.org_staff_create, name='org_staff_create'),
    path('org/staff/<int:user_id>/edit/',
         views.org_staff_edit, name='org_staff_edit'),
    path('org/staff/<int:user_id>/toggle/',
         views.org_staff_toggle, name='org_staff_toggle'),
]