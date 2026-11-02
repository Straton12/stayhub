# network/urls.py
from django.urls import path
from . import views


urlpatterns = [
    path('', views.network_dashboard, name='network_dashboard'),
    path('toggle/', views.toggle_network, name='network_toggle'),

    # Referrals
    path('referral/new/', views.referral_create, name='network_referral_create'),
    path('referral/<int:referral_id>/', views.referral_detail, name='network_referral_detail'),
    path('referral/<int:referral_id>/<str:status>/',
         views.referral_update, name='network_referral_update'),
    path('referral/<int:referral_id>/paid/', views.referral_mark_paid, name='network_referral_paid'),

    # Profile
    path('profile/', views.profile_edit, name='network_profile_edit'),
]