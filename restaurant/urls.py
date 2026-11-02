# restaurant/urls.py
"""
URL configuration for the restaurant app.

Route groups (in order):
    • Dashboard + notifications
    • Restaurant profile + publish (THE one publish action)
    • Menu (+ recipe lines)
    • Orders (+ payment recording)
    • Reservations
    • Suppliers
    • Stock items + movements + adjustments
    • Purchase orders (+ receive → GRN)
    • Goods received notes
    • Receipts
    • Reports
    • AJAX / API

Ordering note: literal paths (e.g. ``stock/movements/``) are declared
BEFORE their parametric siblings (``stock/<int:item_id>/``) so the int
converter doesn't try to match the literal segment.
"""

from django.urls import path

from . import views


urlpatterns = [

    # ============================================================
    #  DASHBOARD
    # ============================================================
    path('', views.restaurant_dashboard, name='restaurant_dashboard'),

    # ============================================================
    #  NOTIFICATIONS
    # ============================================================
    path(
        'notifications/',
        views.notifications_inbox,
        name='restaurant_notifications',
    ),

    # ============================================================
    #  RESTAURANT PROFILE  —  THE ONE PUBLISH ACTION
    # ============================================================
    path(
        'profile/',
        views.restaurant_profile,
        name='restaurant_profile',
    ),
    path(
        'profile/publish-toggle/',
        views.restaurant_publish_toggle,
        name='restaurant_publish_toggle',
    ),

    # ============================================================
    #  MENU
    # ============================================================
    path('menu/', views.menu_list, name='restaurant_menu_list'),
    path('menu/add/', views.menu_add, name='restaurant_menu_add'),

    # --- Recipe lines (bill of materials) ---
    # Declared before the <int:item_id>/edit/ route so 'recipe' is
    # matched literally. (Not strictly required because int converter
    # rejects non-digits, but keeps intent explicit.)
    path(
        'menu/<int:item_id>/recipe/add/',
        views.recipe_line_add,
        name='restaurant_recipe_line_add',
    ),
    path(
        'menu/<int:item_id>/recipe/<int:line_id>/delete/',
        views.recipe_line_delete,
        name='restaurant_recipe_line_delete',
    ),

    path('menu/<int:item_id>/edit/', views.menu_edit, name='restaurant_menu_edit'),

    # ============================================================
    #  ORDERS
    # ============================================================
    path('orders/', views.order_list, name='restaurant_order_list'),
    path('orders/add/', views.order_add, name='restaurant_order_add'),
    path('orders/<int:order_id>/', views.order_detail, name='restaurant_order_detail'),
    path('orders/<int:order_id>/edit/', views.order_edit, name='restaurant_order_edit'),
    path(
        'orders/<int:order_id>/status/<str:new_status>/',
        views.order_status_update,
        name='restaurant_order_status',
    ),

    # --- Record a payment (auto-issues receipt when paid in full) ---
    path(
        'orders/<int:order_id>/pay/',
        views.order_payment_add,
        name='restaurant_order_payment_add',
    ),

    # ============================================================
    #  RESERVATIONS
    # ============================================================
    path(
        'reservations/',
        views.reservation_list,
        name='restaurant_reservation_list',
    ),
    path(
        'reservations/add/',
        views.reservation_add,
        name='restaurant_reservation_add',
    ),
    path(
        'reservations/<int:reservation_id>/',
        views.reservation_detail,
        name='restaurant_reservation_detail',
    ),
    path(
        'reservations/<int:reservation_id>/status/<str:new_status>/',
        views.reservation_status_update,
        name='restaurant_reservation_status',
    ),

    # ============================================================
    #  SUPPLIERS
    # ============================================================
    path('suppliers/', views.supplier_list, name='restaurant_supplier_list'),
    path('suppliers/add/', views.supplier_add, name='restaurant_supplier_add'),
    path(
        'suppliers/<int:supplier_id>/',
        views.supplier_detail,
        name='restaurant_supplier_detail',
    ),
    path(
        'suppliers/<int:supplier_id>/edit/',
        views.supplier_edit,
        name='restaurant_supplier_edit',
    ),

    # ============================================================
    #  STOCK ITEMS
    # ============================================================
    # Literal routes first, then parametric.
    path('stock/', views.stock_list, name='restaurant_stock_list'),
    path('stock/add/', views.stock_add, name='restaurant_stock_add'),

    path(
        'stock/movements/',
        views.stock_movement_list,
        name='restaurant_stock_movement_list',
    ),
    path(
        'stock/movements/add/',
        views.stock_movement_add,
        name='restaurant_stock_movement_add',
    ),

    path('stock/<int:item_id>/', views.stock_detail, name='restaurant_stock_detail'),
    path('stock/<int:item_id>/edit/', views.stock_edit, name='restaurant_stock_edit'),
    path(
        'stock/<int:item_id>/adjust/',
        views.stock_adjust,
        name='restaurant_stock_adjust',
    ),

    # ============================================================
    #  PURCHASE ORDERS
    # ============================================================
    path('purchase-orders/', views.purchase_order_list, name='restaurant_po_list'),
    path('purchase-orders/add/', views.purchase_order_add, name='restaurant_po_add'),
    path(
        'purchase-orders/<int:po_id>/',
        views.purchase_order_detail,
        name='restaurant_po_detail',
    ),
    path(
        'purchase-orders/<int:po_id>/edit/',
        views.purchase_order_edit,
        name='restaurant_po_edit',
    ),
    path(
        'purchase-orders/<int:po_id>/send/',
        views.purchase_order_send,
        name='restaurant_po_send',
    ),
    path(
        'purchase-orders/<int:po_id>/cancel/',
        views.purchase_order_cancel,
        name='restaurant_po_cancel',
    ),
    path(
        'purchase-orders/<int:po_id>/pay/',
        views.purchase_order_pay,
        name='restaurant_po_pay',
    ),

    # --- Receive goods against a PO (creates a GRN) ---
    path(
        'purchase-orders/<int:po_id>/receive/',
        views.grn_add,
        name='restaurant_grn_add',
    ),

    # ============================================================
    #  GOODS RECEIVED NOTES
    # ============================================================
    path('grn/', views.grn_list, name='restaurant_grn_list'),
    path('grn/<int:grn_id>/', views.grn_detail, name='restaurant_grn_detail'),

    # ============================================================
    #  RECEIPTS
    # ============================================================
    path('receipts/', views.receipt_list, name='restaurant_receipt_list'),
    path(
        'receipts/<int:receipt_id>/',
        views.receipt_detail,
        name='restaurant_receipt_detail',
    ),
    path(
        'receipts/<int:receipt_id>/print/',
        views.receipt_print,
        name='restaurant_receipt_print',
    ),
    path('api/profile/upload-image/', views.restaurant_upload_image, name='restaurant_upload_image'),

    # ============================================================
    #  REPORTS
    # ============================================================
    path('reports/', views.reports_dashboard, name='restaurant_reports'),
    path('api/profile/upload-image/', views.restaurant_upload_image, name='restaurant_upload_image'),
    
    # ============================================================
    #  AJAX / API
    # ============================================================
    path(
        'api/stock-levels/',
        views.api_stock_levels,
        name='restaurant_api_stock_levels',
    ),
]