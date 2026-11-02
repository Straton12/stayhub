# payments/urls.py
from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # Entry
    path('start/<int:booking_pk>/', views.initiate, name='initiate'),

    # M-Pesa
    path('mpesa/wait/<int:attempt_pk>/', views.mpesa_wait, name='mpesa_wait'),
    path('mpesa/sandbox/<int:attempt_pk>/confirm/',
         views.mpesa_sandbox_confirm, name='mpesa_sandbox_confirm'),
    path('mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),

    # Card
    path('card/<int:attempt_pk>/', views.card_stub, name='card_stub'),
    path('card/<int:attempt_pk>/sandbox-confirm/',
         views.card_sandbox_confirm, name='card_sandbox_confirm'),

    # Result pages
    path('success/<int:booking_pk>/', views.success, name='success'),
    path('failed/<int:booking_pk>/', views.failed, name='failed'),

    # Receipts
    path('receipt/<int:pk>/', views.receipt_detail, name='receipt_detail'),
    path('receipt/<int:pk>/pdf/', views.receipt_pdf, name='receipt_pdf'),

    # Guest history
    path('history/', views.history, name='history'),

    # Org ledger + cash
    path('org/ledger/', views.org_ledger, name='org_ledger'),
    path('org/booking/<int:booking_pk>/cash/', views.record_cash, name='record_cash'),
]