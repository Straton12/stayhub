# laundry/urls.py
from django.urls import path
from . import views


urlpatterns = [
    # Dashboard
    path('', views.laundry_dashboard, name='laundry_dashboard'),

    # Notifications
    path('notifications/', views.notifications_inbox, name='laundry_notifications'),

    # Services
    path('services/', views.service_list, name='laundry_service_list'),
    path('services/add/', views.service_add, name='laundry_service_add'),
    path('services/<int:service_id>/edit/', views.service_edit, name='laundry_service_edit'),
    path('services/<int:service_id>/publish-toggle/',
         views.service_publish_toggle, name='laundry_service_publish_toggle'),

    # Orders
    path('orders/', views.order_list, name='laundry_order_list'),
    path('orders/add/', views.order_add, name='laundry_order_add'),
    path('orders/<int:order_id>/', views.order_detail, name='laundry_order_detail'),
    path('orders/<int:order_id>/edit/', views.order_edit, name='laundry_order_edit'),
    path('orders/<int:order_id>/status/<str:new_status>/',
         views.order_status_update, name='laundry_order_status'),

    # Supplies
    path('supplies/', views.supply_list, name='laundry_supply_list'),
    path('supplies/add/', views.supply_add, name='laundry_supply_add'),
    path('supplies/<int:supply_id>/edit/', views.supply_edit, name='laundry_supply_edit'),
]