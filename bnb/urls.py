# bnb/urls.py
from django.urls import path

from . import views


urlpatterns = [
    # ==================== DASHBOARD ====================
    path('', views.bnb_dashboard, name='bnb_dashboard'),

    # ==================== NOTIFICATIONS ====================
    # Inbox of every NotificationLog addressed to the org.
    path(
        'notifications/',
        views.notifications_inbox,
        name='bnb_notifications',
    ),
    # Also exposed under a longer alias for templates that expect it.
    path(
        'notifications/inbox/',
        views.notifications_inbox,
        name='bnb_notifications_inbox',
    ),
    path(
        'notifications/<int:notification_id>/read/',
        views.notification_mark_read,
        name='bnb_notification_mark_read',
    ),
    path(
        'notifications/read-all/',
        views.notification_mark_all_read,
        name='bnb_notifications_mark_all_read',
    ),

    # ==================== SECTION LANDING PAGES ====================
    path('properties/', views.properties_home, name='bnb_properties_home'),
    path('bookings/',   views.bookings_home,   name='bnb_bookings_home'),
    path('operations/', views.operations_home, name='bnb_operations_home'),
    path('finance/',    views.finance_home,    name='bnb_finance_home'),
    path('reports/',    views.reports_home,    name='bnb_reports_home'),
    path('settings/',   views.settings_home,   name='bnb_settings_home'),

    # ==================== PROPERTIES ====================
    path('properties/list/', views.property_list, name='bnb_property_list'),
    path('properties/add/', views.property_add, name='bnb_property_add'),
    path(
        'properties/<int:property_id>/',
        views.property_detail,
        name='bnb_property_detail',
    ),
    path(
        'properties/<int:property_id>/edit/',
        views.property_edit,
        name='bnb_property_edit',
    ),
    path(
        'properties/<int:property_id>/delete/',
        views.property_delete,
        name='bnb_property_delete',
    ),
    path(
        'properties/<int:property_id>/publish-toggle/',
        views.property_publish_toggle,
        name='bnb_property_publish_toggle',
    ),
    
    path(
    'finance/invoices/<int:invoice_id>/print/',
    views.invoice_print,
    name='bnb_invoice_print',
    ),

    # ==================== BOOKINGS ====================
    # Contract: the org NEVER creates or edits a booking.
    # Bookings come from the marketplace; the org only approves / declines /
    # checks-in / checks-out / cancels them here.
    path('bookings/list/', views.booking_list, name='bnb_booking_list'),

    # The two views below are kept ONLY so stale template links resolve.
    # Both redirect with a message — see bnb/views.py.
    path('bookings/add/', views.booking_add, name='bnb_booking_add'),
    path(
        'bookings/<int:booking_id>/edit/',
        views.booking_edit,
        name='bnb_booking_edit',
    ),

    path(
        'bookings/<int:booking_id>/',
        views.booking_detail,
        name='bnb_booking_detail',
    ),
    path(
        'bookings/<int:booking_id>/delete/',
        views.booking_delete,
        name='bnb_booking_delete',
    ),
    path(
        'bookings/<int:booking_id>/status/<str:new_status>/',
        views.booking_status_update,
        name='bnb_booking_status',
    ),
    path(
        'bookings/calendar/',
        views.booking_calendar,
        name='bnb_booking_calendar',
    ),

    # ==================== GUESTS ====================
    path('guests/', views.guest_list, name='bnb_guest_list'),
    path('guests/add/', views.guest_add, name='bnb_guest_add'),
    path('guests/<int:guest_id>/', views.guest_detail, name='bnb_guest_detail'),
    path('guests/<int:guest_id>/edit/', views.guest_edit, name='bnb_guest_edit'),

    # ==================== HOUSEKEEPING ====================
    path('housekeeping/', views.housekeeping_list, name='bnb_housekeeping'),
    path('housekeeping/add/', views.housekeeping_add, name='bnb_housekeeping_add'),
    path(
        'housekeeping/<int:task_id>/edit/',
        views.housekeeping_edit,
        name='bnb_housekeeping_edit',
    ),
    path(
        'housekeeping/<int:task_id>/toggle/',
        views.housekeeping_toggle,
        name='bnb_housekeeping_toggle',
    ),
    path(
        'housekeeping/<int:task_id>/delete/',
        views.housekeeping_delete,
        name='bnb_housekeeping_delete',
    ),

    # ==================== MAINTENANCE ====================
    path('maintenance/', views.maintenance_list, name='bnb_maintenance'),
    path('maintenance/add/', views.maintenance_add, name='bnb_maintenance_add'),
    path(
        'maintenance/<int:request_id>/edit/',
        views.maintenance_edit,
        name='bnb_maintenance_edit',
    ),
    path(
        'maintenance/<int:request_id>/delete/',
        views.maintenance_delete,
        name='bnb_maintenance_delete',
    ),

    # ==================== FINANCE ====================
    # ---- Legacy/aggregate dashboards (kept for existing templates) ----
    path(
        'finance/dashboard/',
        views.finance_dashboard,
        name='bnb_finance_dashboard',
    ),
    path(
        'finance/profit-margin/',
        views.finance_profit_margin,
        name='bnb_finance_profit_margin',
    ),

    # ---- NEW: ledger-based financial system ----
    # Primary financial dashboard with range filters + chart.
    path(
        'finance/ledger/',
        views.finance_ledger,
        name='bnb_finance_ledger',
    ),
    # Profit & loss — revenue vs expenses per month, margins, running total.
    path(
        'finance/ledger/profit/',
        views.finance_profit_ledger,
        name='bnb_finance_profit_ledger',
    ),
    # VAT + financial preferences (VAT is entirely optional, off by default).
    path(
        'finance/ledger/settings/',
        views.finance_settings,
        name='bnb_finance_settings',
    ),

    # Expenses
    path('finance/expenses/', views.expense_list, name='bnb_expense_list'),
    path('finance/expenses/add/', views.expense_add, name='bnb_expense_add'),
    path(
        'finance/expenses/<int:expense_id>/edit/',
        views.expense_edit,
        name='bnb_expense_edit',
    ),
    path(
        'finance/expenses/<int:expense_id>/delete/',
        views.expense_delete,
        name='bnb_expense_delete',
    ),
    path(
        'finance/expenses/period/<str:period>/',
        views.finance_expenses_by_period,
        name='bnb_expenses_by_period',
    ),

    # Revenue
    path('finance/revenues/', views.revenue_list, name='bnb_revenue_list'),
    path('finance/revenues/add/', views.revenue_add, name='bnb_revenue_add'),

    # ==================== INVOICES & PAYMENTS ====================
    path('finance/invoices/', views.invoice_list, name='bnb_invoice_list'),
    path('finance/invoices/add/', views.invoice_add, name='bnb_invoice_add'),
    path(
        'finance/invoices/<int:invoice_id>/',
        views.invoice_detail,
        name='bnb_invoice_detail',
    ),

    path('finance/payments/', views.payment_list, name='bnb_payment_list'),
    path('finance/payments/add/', views.payment_add, name='bnb_payment_add'),

    # ==================== STAFF ====================
    path('staff/', views.staff_list, name='bnb_staff_list'),
    path('staff/add/', views.staff_add, name='bnb_staff_add'),
    path('staff/<int:staff_id>/edit/', views.staff_edit, name='bnb_staff_edit'),

    # ==================== REVIEWS ====================
    # Org-side manual entry for off-platform reviews.
    # Guest-submitted reviews come from the marketplace and land on
    # marketplace.Review — the org sees them on the linked listing.
    path('reviews/', views.review_list, name='bnb_review_list'),
    path('reviews/add/', views.review_add, name='bnb_review_add'),

    # ==================== REPORTS ====================
    path('reports/dashboard/', views.reports_dashboard, name='bnb_reports_dashboard'),
    path('reports/occupancy/', views.reports_occupancy, name='bnb_reports_occupancy'),
    path('reports/revenue/', views.reports_revenue, name='bnb_reports_revenue'),
    path('reports/performance/', views.reports_performance, name='bnb_reports_performance'),

    # ==================== AMENITIES ====================
    path('properties/amenities/',
        views.amenities, name='bnb_amenities'),

    path('properties/amenities/add/',
        views.amenity_add, name='bnb_amenity_add'),

    path('properties/amenities/<int:amenity_id>/edit/',
        views.amenity_edit, name='bnb_amenity_edit'),

    path('properties/amenities/<int:amenity_id>/delete/',
        views.amenity_delete, name='bnb_amenity_delete'),

    # ==================== PRICING RULES ====================
    path('properties/pricing-rules/',
         views.pricing_rules, name='bnb_pricing_rules'),
    path('properties/pricing-rules/add/',
         views.pricing_rule_add, name='bnb_pricing_rule_add'),
    path('properties/pricing-rules/<int:rule_id>/edit/',
         views.pricing_rule_edit, name='bnb_pricing_rule_edit'),
    path('properties/pricing-rules/<int:rule_id>/delete/',
         views.pricing_rule_delete, name='bnb_pricing_rule_delete'),
    path('properties/pricing-rules/<int:rule_id>/toggle/',
         views.pricing_rule_toggle, name='bnb_pricing_rule_toggle'),

    # ==================== SETTINGS ====================
    path('settings/general/', views.settings_general, name='bnb_settings_general'),
    path('settings/team/', views.settings_team, name='bnb_settings_team'),
    path('settings/billing/', views.settings_billing, name='bnb_settings_billing'),
    
    
        # Expense categories
    path(
        'finance/expenses/categories/',
        views.expense_category_list,
        name='bnb_expense_category_list',
    ),
    path(
        'finance/expenses/categories/add/',
        views.expense_category_add,
        name='bnb_expense_category_add',
    ),
    path(
        'finance/expenses/categories/<int:pk>/edit/',
        views.expense_category_edit,
        name='bnb_expense_category_edit',
    ),
    path(
        'finance/expenses/categories/<int:pk>/delete/',
        views.expense_category_delete,
        name='bnb_expense_category_delete',
    ),
]