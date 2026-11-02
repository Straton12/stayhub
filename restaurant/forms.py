# restaurant/forms.py
"""
All restaurant-app forms.

Layout:
    • Helpers (widget shortcuts, BaseStyledForm)
    • Restaurant profile (publish to marketplace)   ← the ONE publish form
    • Menu
        - MenuItemForm
        - RecipeLineForm
    • Orders
        - OrderForm
        - OrderPaymentForm
    • Reservations
        - ReservationForm
    • Suppliers
        - SupplierForm
    • Stock
        - StockItemForm
        - StockMovementForm
        - StockAdjustForm
    • Procurement
        - PurchaseOrderForm
        - POLineForm
        - GRNForm
        - GRNLineForm
    • Receipts
        - ReceiptForm
"""

from django import forms
from django.core.exceptions import ValidationError

from .models import (
    GoodsReceivedNote,
    MenuItem,
    Order,
    PurchaseOrder,
    Receipt,
    Reservation,
    RestaurantProfile,
    StockItem,
    StockMovement,
    Supplier,
)


# ============================================================
#  HELPERS
# ============================================================
def _input(**kw):
    """Text input with the shared .input class and any extras."""
    return forms.TextInput(attrs={'class': 'input', **kw})


def _textarea(rows=3, **kw):
    return forms.Textarea(attrs={'class': 'input', 'rows': rows, **kw})


def _number(**kw):
    return forms.NumberInput(attrs={'class': 'input', **kw})


def _email(**kw):
    return forms.EmailInput(attrs={'class': 'input', **kw})


def _url(**kw):
    return forms.URLInput(attrs={'class': 'input', **kw})


class BaseStyledForm(forms.ModelForm):
    """
    Apply the `.input` class to any widget that hasn't already
    declared it. Keeps templates simple: no manual {% add_class %}
    filters, no per-form widget dicts unless we want placeholders.
    """
    input_class = 'input'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        styled_widgets = (
            forms.TextInput,
            forms.NumberInput,
            forms.EmailInput,
            forms.URLInput,
            forms.Textarea,
            forms.Select,
            forms.DateInput,
            forms.DateTimeInput,
            forms.TimeInput,
        )
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, styled_widgets):
                classes = widget.attrs.get('class', '')
                if self.input_class not in classes:
                    widget.attrs['class'] = (classes + ' ' + self.input_class).strip()


# ============================================================
#  RESTAURANT PROFILE  —  THE ONE PUBLISH FORM
# ============================================================
class RestaurantProfileForm(BaseStyledForm):
    """
    The single publish action for the restaurant.

    Saving this form mirrors everything onto the marketplace
    `Listing` (via `_ensure_restaurant_listing(profile)` in views.py),
    so the whole storefront — brand, location, contact, socials,
    hours, policies, and menu — goes live (or is hidden) in one go.
    """

    # Gallery images come in as free-text lines and are turned into a
    # list before saving.
    gallery_images_text = forms.CharField(
        required=False,
        widget=_textarea(
            rows=3,
            placeholder='https://…/image1.jpg\nhttps://…/image2.jpg',
        ),
        label='Gallery image URLs (one per line, max 4)',
        help_text='These appear on the public restaurant page. '
                  'The cover image is uploaded separately.',
    )

    # Opening hours come in as "key: value" lines and become a dict.
    opening_hours_text = forms.CharField(
        required=False,
        widget=_textarea(
            rows=7,
            placeholder='mon: 08:00-22:00\ntue: 08:00-22:00\n'
                        'wed: 08:00-22:00\nthu: 08:00-22:00\n'
                        'fri: 08:00-23:00\nsat: 09:00-23:00\nsun: closed',
        ),
        label='Opening hours (one per line)',
        help_text='Format: key: HH:MM-HH:MM or "closed". '
                  'Keys: mon / tue / wed / thu / fri / sat / sun.',
    )

    class Meta:
        model = RestaurantProfile
        fields = [
            # ---------- Brand ----------
            'name', 'tagline', 'short_description', 'description',
            'logo', 'cover_image',

            # ---------- Location ----------
            'address', 'city', 'location_label', 'latitude', 'longitude',

            # ---------- Contact ----------
            'phone', 'email', 'whatsapp',

            # ---------- Socials ----------
            'website', 'facebook', 'instagram',
            'twitter', 'tiktok', 'youtube',

            # ---------- Commercial ----------
            'cuisine', 'price_range', 'min_order_amount',
            'delivery_fee', 'delivery_radius_km', 'average_prep_time',

            # ---------- Hours ----------
            'is_open_now',

            # ---------- Marketplace publishing ----------
            'publish_to_marketplace',
            'payment_policy', 'deposit_percent', 'service_fee_percent',
            'cancellation_policy', 'house_rules',
        ]
        widgets = {
            'name': _input(placeholder="e.g. Mama Oliech's Kitchen"),
            'tagline': _input(placeholder='Home-style Kenyan food, delivered fast'),
            'short_description': _input(maxlength=280),
            'description': _textarea(rows=4),
            'address': _input(placeholder='123 Biashara Street'),
            'city': _input(placeholder='Nairobi'),
            'location_label': _input(placeholder='Westlands, Nairobi'),
            'phone': _input(placeholder='+254712345678'),
            'email': _email(placeholder='hello@restaurant.co.ke'),
            'whatsapp': _input(placeholder='+254712345678'),
            'website': _url(placeholder='https://…'),
            'facebook': _url(placeholder='https://facebook.com/…'),
            'instagram': _url(placeholder='https://instagram.com/…'),
            'twitter': _url(placeholder='https://x.com/…'),
            'tiktok': _url(placeholder='https://tiktok.com/@…'),
            'youtube': _url(placeholder='https://youtube.com/@…'),
            'cuisine': _input(placeholder='Kenyan, Fast Food, Grills'),
            'house_rules': _textarea(
                rows=3,
                placeholder='No outside food\n'
                            'Allergen info available on request\n'
                            'Minimum order KES 500',
            ),
            'min_order_amount': _number(min=0, step='0.01'),
            'delivery_fee': _number(min=0, step='0.01'),
            'delivery_radius_km': _number(min=0),
            'average_prep_time': _number(min=0),
            'deposit_percent': _number(min=0, max=100),
            'service_fee_percent': _number(min=0, max=100, step='0.01'),
            'latitude': _number(step='0.000001'),
            'longitude': _number(step='0.000001'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Populate the two "text" fields from the existing instance
        if self.instance and self.instance.pk:
            self.fields['gallery_images_text'].initial = '\n'.join(
                self.instance.gallery_images or []
            )
            self.fields['opening_hours_text'].initial = '\n'.join(
                f'{k}: {v}' for k, v in (self.instance.opening_hours or {}).items()
            )
        else:
            self.fields['publish_to_marketplace'].initial = True
            self.fields['payment_policy'].initial = 'pay_on_delivery'
            self.fields['price_range'].initial = 'mid'
            self.fields['is_open_now'].initial = True

    # -------- cleaners --------
    def clean_gallery_images_text(self):
        raw = (self.cleaned_data.get('gallery_images_text') or '').strip()
        urls = [u.strip() for u in raw.splitlines() if u.strip()]
        if len(urls) > 4:
            raise ValidationError('You can add at most 4 gallery images.')
        for u in urls:
            if not (u.startswith('http://') or u.startswith('https://')):
                raise ValidationError(f'Invalid image URL: {u}')
        return urls

    def clean_opening_hours_text(self):
        raw = (self.cleaned_data.get('opening_hours_text') or '').strip()
        valid_keys = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}
        hours = {}
        for line in raw.splitlines():
            if ':' not in line:
                continue
            k, v = line.split(':', 1)
            k = k.strip().lower()
            v = v.strip()
            if not k or not v:
                continue
            if k not in valid_keys:
                raise ValidationError(
                    f'Invalid day key "{k}". '
                    f'Use mon / tue / wed / thu / fri / sat / sun.'
                )
            hours[k] = v
        return hours

    def clean_min_order_amount(self):
        v = self.cleaned_data.get('min_order_amount') or 0
        if v < 0:
            raise ValidationError('Minimum order cannot be negative.')
        return v

    def clean_delivery_fee(self):
        v = self.cleaned_data.get('delivery_fee') or 0
        if v < 0:
            raise ValidationError('Delivery fee cannot be negative.')
        return v

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.gallery_images = self.cleaned_data.get('gallery_images_text') or []
        profile.opening_hours = self.cleaned_data.get('opening_hours_text') or {}
        if commit:
            profile.save()
        return profile


# ============================================================
#  MENU
# ============================================================
class MenuItemForm(BaseStyledForm):
    """
    Creates / edits a single dish.

    A dish is INTERNAL — it does not have its own marketplace listing.
    Publishing happens on the restaurant profile. When the restaurant
    is published, every available dish is shown inside its storefront.
    """

    class Meta:
        model = MenuItem
        fields = [
            'name', 'category', 'price', 'cost_price',
            'short_description', 'description', 'cover_image_url',
            'preparation_time', 'is_vegetarian', 'is_spicy', 'allergens',
            'is_available',
        ]
        widgets = {
            'name': _input(placeholder='e.g. Beef Burger'),
            'short_description': _input(maxlength=280),
            'description': _textarea(rows=4),
            'cover_image_url': _input(placeholder='https://…/cover.jpg'),
            'allergens': _input(placeholder='nuts, dairy, gluten'),
            'preparation_time': _number(min=1),
            'cost_price': _number(min=0, step='0.01'),
            'price': _number(min=0, step='0.01'),
        }

    def clean_price(self):
        p = self.cleaned_data.get('price') or 0
        if p < 0:
            raise ValidationError('Price cannot be negative.')
        return p

    def clean_cost_price(self):
        c = self.cleaned_data.get('cost_price') or 0
        if c < 0:
            raise ValidationError('Cost cannot be negative.')
        return c


class RecipeLineForm(forms.Form):
    """Add one ingredient → menu item link (bill of materials)."""

    stock_item = forms.ModelChoiceField(
        queryset=StockItem.objects.none(),
        widget=forms.Select(attrs={'class': 'input'}),
        label='Ingredient',
    )
    quantity = forms.DecimalField(
        min_value=0.01, max_digits=12, decimal_places=2,
        widget=_number(step='0.01', min='0.01'),
        label='Quantity per item',
    )
    notes = forms.CharField(
        required=False, max_length=200,
        widget=_input(placeholder='Optional note'),
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields['stock_item'].queryset = StockItem.objects.filter(
                organization=organization, is_active=True,
            ).order_by('name')


# ============================================================
#  ORDERS
# ============================================================
class OrderForm(BaseStyledForm):
    class Meta:
        model = Order
        fields = [
            'customer_name', 'customer_phone', 'customer_address',
            'order_type', 'source', 'payment_policy', 'delivery_fee',
            'special_instructions', 'notes',
        ]
        widgets = {
            'customer_name': _input(),
            'customer_phone': _input(),
            'customer_address': _input(),
            'special_instructions': _textarea(rows=2),
            'notes': _textarea(rows=2),
            'delivery_fee': _number(min=0, step='0.01'),
        }


class OrderPaymentForm(forms.Form):
    """Record a payment against an Order."""

    amount = forms.DecimalField(
        min_value=0.01, max_digits=12, decimal_places=2,
        widget=_number(step='0.01'),
    )
    method = forms.ChoiceField(
        choices=Receipt.PAYMENT_METHODS,
        widget=forms.Select(attrs={'class': 'input'}),
        initial='cash',
    )
    reference = forms.CharField(
        required=False, max_length=120,
        widget=_input(placeholder='e.g. M-Pesa code / transaction id'),
    )

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        if order is not None:
            self.fields['amount'].initial = order.balance
            self.fields['amount'].widget.attrs['max'] = str(order.balance)


# ============================================================
#  RESERVATIONS
# ============================================================
class ReservationForm(BaseStyledForm):
    class Meta:
        model = Reservation
        fields = [
            'customer_name', 'customer_phone', 'customer_email',
            'guests', 'reservation_time', 'table_preference', 'notes',
        ]
        widgets = {
            'customer_name': _input(),
            'customer_phone': _input(),
            'customer_email': _email(),
            'reservation_time': forms.DateTimeInput(
                attrs={'class': 'input', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'table_preference': _input(),
            'notes': _textarea(rows=2),
            'guests': _number(min=1),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reservation_time'].input_formats = ('%Y-%m-%dT%H:%M',)


# ============================================================
#  SUPPLIERS
# ============================================================
class SupplierForm(BaseStyledForm):
    class Meta:
        model = Supplier
        fields = [
            'name', 'phone', 'email', 'address', 'supplies',
            'reorder_level', 'notes', 'is_active',
        ]
        widgets = {
            'name': _input(),
            'phone': _input(),
            'email': _email(),
            'address': _input(),
            'supplies': _input(),
            'reorder_level': _input(),
            'notes': _textarea(rows=2),
        }


# ============================================================
#  STOCK
# ============================================================
class StockItemForm(BaseStyledForm):
    opening_qty = forms.DecimalField(
        required=False, min_value=0, max_digits=12, decimal_places=2,
        widget=_number(step='0.01', min=0),
        label='Opening stock (optional)',
        help_text='Creates an initial “in” stock movement.',
    )

    class Meta:
        model = StockItem
        fields = [
            'name', 'sku', 'category', 'unit',
            'unit_cost', 'reorder_level', 'is_active', 'notes',
        ]
        widgets = {
            'name': _input(),
            'sku': _input(),
            'unit_cost': _number(step='0.01', min=0),
            'reorder_level': _number(step='0.01', min=0),
            'notes': _textarea(rows=2),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['opening_qty'].widget = forms.HiddenInput()


class StockMovementForm(BaseStyledForm):
    class Meta:
        model = StockMovement
        fields = ['stock_item', 'movement_type', 'quantity', 'unit_cost', 'reason']
        widgets = {
            'stock_item': forms.Select(attrs={'class': 'input'}),
            'movement_type': forms.Select(attrs={'class': 'input'}),
            'quantity': _number(step='0.01', min='0.01'),
            'unit_cost': _number(step='0.01', min=0),
            'reason': _input(placeholder='e.g. Opening stock / spoilage / restock'),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields['stock_item'].queryset = StockItem.objects.filter(
                organization=organization, is_active=True,
            ).order_by('name')

    def clean_quantity(self):
        q = self.cleaned_data.get('quantity') or 0
        if q <= 0:
            raise ValidationError('Quantity must be greater than zero.')
        return q


class StockAdjustForm(forms.Form):
    """Set stock to the physical count entered here."""

    counted = forms.DecimalField(
        min_value=0, max_digits=12, decimal_places=2,
        widget=_number(step='0.01', min=0),
        label='Physical count',
    )
    reason = forms.CharField(
        required=False, max_length=200,
        widget=_input(placeholder='e.g. End-of-month count'),
    )


# ============================================================
#  PROCUREMENT
# ============================================================
class PurchaseOrderForm(BaseStyledForm):
    class Meta:
        model = PurchaseOrder
        fields = ['supplier', 'expected_date', 'notes']
        widgets = {
            'supplier': forms.Select(attrs={'class': 'input'}),
            'expected_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'notes': _textarea(rows=2),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields['supplier'].queryset = Supplier.objects.filter(
                organization=organization, is_active=True,
            ).order_by('name')


class POLineForm(forms.Form):
    """One line on a purchase order."""

    stock_item = forms.ModelChoiceField(
        queryset=StockItem.objects.none(),
        widget=forms.Select(attrs={'class': 'input'}),
    )
    quantity = forms.DecimalField(
        min_value=0.01, max_digits=12, decimal_places=2,
        widget=_number(step='0.01'),
    )
    unit_cost = forms.DecimalField(
        min_value=0, max_digits=12, decimal_places=2,
        widget=_number(step='0.01'),
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields['stock_item'].queryset = StockItem.objects.filter(
                organization=organization, is_active=True,
            ).order_by('name')


class GRNForm(BaseStyledForm):
    """Header for a Goods Received Note."""

    class Meta:
        model = GoodsReceivedNote
        fields = ['received_date', 'notes']
        widgets = {
            'received_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'notes': _textarea(rows=2),
        }


class GRNLineForm(forms.Form):
    """Per-line receipt quantity."""

    line_id = forms.IntegerField(widget=forms.HiddenInput())
    quantity_received = forms.DecimalField(
        min_value=0, max_digits=12, decimal_places=2,
        widget=_number(step='0.01', min=0),
    )


# ============================================================
#  RECEIPTS
# ============================================================
class ReceiptForm(BaseStyledForm):
    """Manual issue of a receipt (usually auto-issued via order payment)."""

    class Meta:
        model = Receipt
        fields = ['amount', 'method', 'reference', 'notes']
        widgets = {
            'amount': _number(step='0.01', min=0),
            'method': forms.Select(attrs={'class': 'input'}),
            'reference': _input(placeholder='e.g. M-Pesa code'),
            'notes': _textarea(rows=2),
        }


# ============================================================
#  PUBLIC EXPORTS
# ============================================================
__all__ = [
    # The one publish form
    'RestaurantProfileForm',
    # Menu
    'MenuItemForm',
    'RecipeLineForm',
    # Orders
    'OrderForm',
    'OrderPaymentForm',
    # Reservations
    'ReservationForm',
    # Suppliers
    'SupplierForm',
    # Stock
    'StockItemForm',
    'StockMovementForm',
    'StockAdjustForm',
    # Procurement
    'PurchaseOrderForm',
    'POLineForm',
    'GRNForm',
    'GRNLineForm',
    # Receipts
    'ReceiptForm',
]