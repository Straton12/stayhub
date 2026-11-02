# tours/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path('', views.tours_dashboard, name='tours_dashboard'),

    # Notifications
    path('notifications/', views.notifications_inbox, name='tours_notifications'),

    # Packages
    path('packages/', views.package_list, name='tours_package_list'),
    path('packages/add/', views.package_add, name='tours_package_add'),
    path('packages/<int:package_id>/edit/',
         views.package_edit, name='tours_package_edit'),
    path('packages/<int:package_id>/publish-toggle/',
         views.package_publish_toggle, name='tours_package_publish_toggle'),

    # Bookings
    path('bookings/', views.booking_list, name='tours_booking_list'),
    path('bookings/add/', views.booking_add, name='tours_booking_add'),
    path('bookings/<int:booking_id>/', views.booking_detail, name='tours_booking_detail'),
    path('bookings/<int:booking_id>/edit/', views.booking_edit, name='tours_booking_edit'),
    path('bookings/<int:booking_id>/status/<str:new_status>/',
         views.booking_status_update, name='tours_booking_status'),

    # Guides
    path('guides/', views.guide_list, name='tours_guide_list'),
    path('guides/add/', views.guide_add, name='tours_guide_add'),
    path('guides/<int:guide_id>/edit/', views.guide_edit, name='tours_guide_edit'),

    # Vehicles
    path('vehicles/', views.vehicle_list, name='tours_vehicle_list'),
    path('vehicles/add/', views.vehicle_add, name='tours_vehicle_add'),
    path('vehicles/<int:vehicle_id>/edit/', views.vehicle_edit, name='tours_vehicle_edit'),
]