# bnb/forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import (
    Property, Guest, Booking, HousekeepingTask, MaintenanceRequest,
    Expense, ExpenseCategory, Revenue, Invoice, Payment,
    StaffMember, Review, Amenity,
)


# BnB-only category slugs. Any marketplace category NOT in this list
# (tours, food, laundry, transport, …) is excluded from the property form.
BNB_ALLOWED_CATEGORY_SLUGS = (
    'stays',
)


# ---------------------------------------------------------------------------
#  Property — one form for everything
# ---------------------------------------------------------------------------
class PropertyForm(forms.ModelForm):
    """
    Single Property form.

    Covers: identity, location, contact, socials, commercial terms,
    check-in/out times, amenities (multi-select from the org's Amenity
    library), house rules, the 4 image slots, and a form-only
    "publish to marketplace" toggle.
    """

    # Form-only field.
    publish_to_marketplace = forms.BooleanField(
        required=False,
        initial=True,
        label='Publish to marketplace',
        help_text='When checked, this property appears on the public marketplace immediately.',
        widget=forms.CheckboxInput(attrs={'class': 'pf-publish-check'}),
    )

    # -------------------------------------------------------------------
    #  Amenities — dropdown to add + chips to remove
    # -------------------------------------------------------------------
    # `amenities_picker` is the DROPDOWN (pick one, JS adds a chip).
    # `amenities_value` is the HIDDEN field that carries the final
    # newline-separated list back to `Property.amenities` on save.
    amenities_picker = forms.ModelChoiceField(
        queryset=Amenity.objects.none(),      # set per-org in __init__
        required=False,
        label='Amenities',
        widget=forms.Select(attrs={
            'class': 'pf-amenity-select',
            'data-amenity-picker': '1',
        }),
    )

    amenities_value = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'data-amenity-value': '1'}),
    )


    class Meta:
        model = Property
        # NOTE: `amenities` is excluded — it's presented via `amenities_picker`.
        fields = [
            # Identity
            'name', 'category', 'short_description', 'description',
            # Location
            'location_label', 'address', 'latitude', 'longitude',
            # Contact
            'phone', 'email', 'whatsapp',
            # Socials
            'website', 'facebook', 'instagram', 'twitter', 'tiktok', 'youtube',
            # Commercial
            'price', 'price_unit', 'min_nights', 'max_guests',
            'bedrooms', 'baths',
            # Times
            'check_in_time', 'check_out_time',
            # Rules (amenities handled via `amenities_picker`)
            'house_rules',
            # Images (cover + up to 3 extras)
            'cover_image', 'image_2', 'image_3', 'image_4',
            # Toggle
            'is_active',
        ]

        widgets = {
            # Identity
            'name': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'e.g. Westlands Skyline Apartments',
            }),
            'short_description': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'One-line summary (max 280 chars)',
            }),
            'description': forms.Textarea(attrs={
                'class': 'input', 'rows': 5,
                'placeholder': 'Describe what makes this property special…',
            }),

            # Location
            'location_label': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'e.g. Westlands, Nairobi',
            }),
            'address': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'Street / building / landmark',
            }),
            'latitude': forms.NumberInput(attrs={
                'class': 'input', 'step': '0.000001', 'placeholder': '-1.292066',
            }),
            'longitude': forms.NumberInput(attrs={
                'class': 'input', 'step': '0.000001', 'placeholder': '36.821945',
            }),

            # Contact
            'phone': forms.TextInput(attrs={
                'class': 'input', 'placeholder': '+254 712 345 678',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'input', 'placeholder': 'hello@example.com',
            }),
            'whatsapp': forms.TextInput(attrs={
                'class': 'input', 'placeholder': '+254712345678',
            }),

            # Socials
            'website': forms.URLInput(attrs={
                'class': 'input', 'placeholder': 'https://your-site.com',
            }),
            'facebook': forms.URLInput(attrs={
                'class': 'input', 'placeholder': 'https://facebook.com/yourpage',
            }),
            'instagram': forms.URLInput(attrs={
                'class': 'input', 'placeholder': 'https://instagram.com/you',
            }),
            'twitter': forms.URLInput(attrs={
                'class': 'input', 'placeholder': 'https://x.com/you',
            }),
            'tiktok': forms.URLInput(attrs={
                'class': 'input', 'placeholder': 'https://tiktok.com/@you',
            }),
            'youtube': forms.URLInput(attrs={
                'class': 'input', 'placeholder': 'https://youtube.com/@you',
            }),

            # Commercial
            'price': forms.NumberInput(attrs={
                'class': 'input', 'min': 0, 'step': '0.01',
            }),
            'price_unit': forms.TextInput(attrs={
                'class': 'input', 'placeholder': 'per night',
            }),

            # Times
            'check_in_time': forms.TextInput(attrs={
                'class': 'input', 'placeholder': '14:00',
            }),
            'check_out_time': forms.TextInput(attrs={
                'class': 'input', 'placeholder': '10:00',
            }),

            # Rules
            'house_rules': forms.Textarea(attrs={
                'class': 'input', 'rows': 4,
                'placeholder': 'One per line, e.g.\nNo smoking\nNo pets\nQuiet hours 22:00–07:00',
            }),
        }

    # ---- Init ------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Default the publish checkbox
        if self.instance and self.instance.pk:
            listing = getattr(self.instance, 'listing', None)
            if listing is not None:
                self.fields['publish_to_marketplace'].initial = (
                    listing.status == 'approved' and listing.is_active
                )
            else:
                self.fields['publish_to_marketplace'].initial = False
        else:
            self.fields['publish_to_marketplace'].initial = True

        # ----------------------------------------------
        #  Category: restrict to BnB categories
        # ----------------------------------------------
        try:
            from marketplace.models import ListingCategory

            allowed_slugs = list(BNB_ALLOWED_CATEGORY_SLUGS)

            current_cat_id = None
            if self.instance and self.instance.pk and self.instance.category_id:
                current_cat_id = self.instance.category_id
                current_slug = getattr(self.instance.category, 'slug', None)
                if current_slug and current_slug not in allowed_slugs:
                    allowed_slugs.append(current_slug)

            if 'stays' in allowed_slugs:
                ListingCategory.objects.get_or_create(
                    slug='stays',
                    defaults={
                        'name': 'Stays',
                        'icon': 'bed',
                        'accent': 'indigo',
                        'display_order': 10,
                    },
                )

            self.fields['category'].queryset = (
                ListingCategory.objects
                .filter(slug__in=allowed_slugs)
                .order_by('display_order', 'name')
            )

            if current_cat_id:
                if not self.fields['category'].queryset.filter(pk=current_cat_id).exists():
                    current_obj = ListingCategory.objects.filter(pk=current_cat_id).first()
                    if current_obj:
                        self.fields['category'].queryset = (
                            ListingCategory.objects
                            .filter(
                                Q(pk=current_cat_id) |
                                Q(slug__in=allowed_slugs)
                            )
                            .order_by('display_order', 'name')
                        )

            self.fields['category'].empty_label = '— Choose a category —'
            self.fields['category'].help_text = ''

        except Exception:
            pass

        # ----------------------------------------------
        #  Amenities: populate picker from the org's library
        # ----------------------------------------------
        try:
            org = None
            if self.instance and self.instance.pk and self.instance.organization_id:
                org = self.instance.organization
            else:
                org = getattr(self.instance, 'organization', None)

            if org is not None:
                self.fields['amenities_picker'].queryset = (
                    Amenity.objects
                    .filter(organization=org, is_active=True)
                    .order_by('category', 'display_order', 'name')
                )
            else:
                self.fields['amenities_picker'].queryset = Amenity.objects.none()

            # ---- Pre-select current amenities (edit mode) ----
            if self.instance and self.instance.pk:
                current_names = [
                    a.strip()
                    for a in (self.instance.amenities or '').splitlines()
                    if a.strip()
                ]
                if current_names:
                    qs = self.fields['amenities_picker'].queryset
                    matched_ids = list(
                        qs.filter(name__in=current_names).values_list('id', flat=True)
                    )
                    self.fields['amenities_picker'].initial = matched_ids

        except Exception:
            pass

    # ---- Validation ------------------------------------------------------
    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if len(name) < 2:
            raise ValidationError('Please enter a property name.')
        return name

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price < 0:
            raise ValidationError('Price cannot be negative.')
        return price

    def clean_max_guests(self):
        n = self.cleaned_data.get('max_guests') or 1
        if n < 1:
            raise ValidationError('Max guests must be at least 1.')
        return n

    def clean_whatsapp(self):
        v = (self.cleaned_data.get('whatsapp') or '').strip()
        if v and not any(ch.isdigit() for ch in v):
            raise ValidationError('WhatsApp number must contain digits.')
        return v

    def clean(self):
        cleaned = super().clean()
        lat = cleaned.get('latitude')
        lng = cleaned.get('longitude')

        if lat is not None and not (-90 <= float(lat) <= 90):
            self.add_error('latitude', 'Latitude must be between -90 and 90.')
        if lng is not None and not (-180 <= float(lng) <= 180):
            self.add_error('longitude', 'Longitude must be between -180 and 180.')

        # Require a cover image only for new properties
        if not self.instance.pk:
            has_file = bool(cleaned.get('cover_image'))
            if not has_file:
                self.add_error('cover_image', 'Please upload a cover image.')

        return cleaned

    def save(self, commit=True):
        """
        Read the hidden `amenities_value` (newline-separated list of names)
        and write it into `Property.amenities`.
        """
        instance = super().save(commit=False)

        try:
            raw = self.cleaned_data.get('amenities_value') or ''
            names = [n.strip() for n in raw.splitlines() if n.strip()]

            # Deduplicate (case-insensitive), keep order
            seen = set()
            ordered = []
            for n in names:
                key = n.lower()
                if key not in seen:
                    seen.add(key)
                    ordered.append(n)

            instance.amenities = '\n'.join(ordered)
        except Exception:
            pass

        if commit:
            instance.save()
            self.save_m2m()

        return instance


# ---------------------------------------------------------------------------
#  Guests
# ---------------------------------------------------------------------------
class GuestForm(forms.ModelForm):
    class Meta:
        model = Guest
        fields = ['full_name', 'email', 'phone', 'country', 'id_number', 'notes']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'input'}),
            'email': forms.EmailInput(attrs={'class': 'input'}),
            'phone': forms.TextInput(attrs={'class': 'input'}),
            'country': forms.TextInput(attrs={'class': 'input'}),
            'id_number': forms.TextInput(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }

    def clean_full_name(self):
        name = (self.cleaned_data.get('full_name') or '').strip()
        if len(name) < 2:
            raise ValidationError('Please enter the guest name.')
        return name


# ---------------------------------------------------------------------------
#  Booking
# ---------------------------------------------------------------------------
class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = [
            'property', 'guest',
            'guest_name', 'guest_email', 'guest_phone',
            'check_in', 'check_out',
            'adults', 'children',
            'status', 'source',
            'total_amount', 'amount_paid',
            'cleaning_fee', 'tax_amount',
            'notes', 'special_requests',
        ]
        widgets = {
            'property': forms.Select(attrs={'class': 'input'}),
            'guest': forms.Select(attrs={'class': 'input'}),
            'guest_name': forms.TextInput(attrs={'class': 'input'}),
            'guest_email': forms.EmailInput(attrs={'class': 'input'}),
            'guest_phone': forms.TextInput(attrs={'class': 'input'}),
            'check_in': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
            'check_out': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
            'adults': forms.NumberInput(attrs={'class': 'input', 'min': 1}),
            'children': forms.NumberInput(attrs={'class': 'input', 'min': 0}),
            'status': forms.Select(attrs={'class': 'input'}),
            'source': forms.Select(attrs={'class': 'input'}),
            'total_amount': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'amount_paid': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'cleaning_fee': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'tax_amount': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
            'special_requests': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default to nothing — the view sets the per-org queryset.
        self.fields['property'].queryset = Property.objects.none()
        self.fields['guest'].required = False

    def clean(self):
        cleaned = super().clean()
        ci = cleaned.get('check_in')
        co = cleaned.get('check_out')
        if ci and co and co <= ci:
            self.add_error('check_out', 'Check-out must be after check-in.')
        return cleaned


# ---------------------------------------------------------------------------
#  Housekeeping / Maintenance
# ---------------------------------------------------------------------------
class HousekeepingTaskForm(forms.ModelForm):
    class Meta:
        model = HousekeepingTask
        fields = [
            'property', 'task_type', 'description', 'assigned_to',
            'priority', 'status', 'scheduled_for', 'cost',
        ]
        widgets = {
            'property': forms.Select(attrs={'class': 'input'}),
            'task_type': forms.Select(attrs={'class': 'input'}),
            'description': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'e.g. Clean room 2B before next arrival',
            }),
            'assigned_to': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'Staff name',
            }),
            'priority': forms.Select(attrs={'class': 'input'}),
            'status': forms.Select(attrs={'class': 'input'}),
            'scheduled_for': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'input',
            }),
            'cost': forms.NumberInput(attrs={
                'class': 'input',
                'step': '0.01',
                'min': '0',
                'value': '0',
            }),
        }


class MaintenanceRequestForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = [
            'property', 'category', 'issue', 'description', 'reported_by',
            'assigned_to', 'priority', 'status', 'cost',
        ]
        widgets = {
            'property': forms.Select(attrs={'class': 'input'}),
            'category': forms.Select(attrs={'class': 'input'}),
            'issue': forms.TextInput(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'input'}),
            'reported_by': forms.TextInput(attrs={'class': 'input'}),
            'assigned_to': forms.TextInput(attrs={'class': 'input'}),
            'priority': forms.Select(attrs={'class': 'input'}),
            'status': forms.Select(attrs={'class': 'input'}),
            'cost': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['property'].queryset = Property.objects.none()


# ---------------------------------------------------------------------------
#  Finance
# ---------------------------------------------------------------------------
class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            'property', 'category', 'title', 'description',
            'amount', 'frequency', 'payment_method', 'vendor',
            'expense_date', 'paid', 'receipt', 'notes',
        ]
        widgets = {
            'property': forms.Select(attrs={'class': 'input'}),
            'category': forms.Select(attrs={'class': 'input'}),
            'title': forms.TextInput(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
            'amount': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'frequency': forms.Select(attrs={'class': 'input'}),
            'payment_method': forms.Select(attrs={'class': 'input'}),
            'vendor': forms.TextInput(attrs={'class': 'input'}),
            'expense_date': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
            'receipt': forms.ClearableFileInput(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount') or 0
        if amount < 0:
            raise ValidationError('Amount cannot be negative.')
        return amount


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ['name', 'description', 'is_recurring']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }


class RevenueForm(forms.ModelForm):
    class Meta:
        model = Revenue
        fields = [
            'property', 'booking', 'title', 'source', 'amount',
            'revenue_date', 'notes',
        ]
        widgets = {
            'property': forms.Select(attrs={'class': 'input'}),
            'booking': forms.Select(attrs={'class': 'input'}),
            'title': forms.TextInput(attrs={'class': 'input'}),
            'source': forms.Select(attrs={'class': 'input'}),
            'amount': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'revenue_date': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'type': 'date', 'class': 'input'},
            ),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Accept ISO (browser) + DD/MM/YYYY (manual) + a couple of safe fallbacks
        self.fields['revenue_date'].input_formats = [
            '%Y-%m-%d',      # 2026-10-19  ← what <input type="date"> submits
            '%d/%m/%Y',      # 19/10/2026
            '%d %b %Y',      # 19 Oct 2026
            '%d %B %Y',      # 19 October 2026
            '%m/%d/%Y',      # 10/19/2026
        ]
        # Force the rendered value to ISO so the browser date input accepts it
        self.fields['revenue_date'].widget.format = '%Y-%m-%d'

        # These are optional in the model (null=True, blank=True)
        self.fields['property'].required = False
        self.fields['booking'].required = False

        # Clear empty labels for the selects
        self.fields['property'].empty_label = '— No property —'
        self.fields['booking'].empty_label = '— No linked booking —'

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None:
            raise ValidationError('Please enter an amount.')
        if amount < 0:
            raise ValidationError('Amount cannot be negative.')
        return amount

    def clean_revenue_date(self):
        d = self.cleaned_data.get('revenue_date')
        if d is None:
            raise ValidationError('Please enter a date.')
        return d


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            'booking', 'invoice_number', 'guest_name', 'guest_email',
            'issue_date', 'due_date',
            'subtotal', 'tax_amount', 'total', 'amount_paid',
            'status', 'notes',
        ]
        widgets = {
            'booking': forms.Select(attrs={'class': 'input'}),
            'invoice_number': forms.TextInput(attrs={'class': 'input'}),
            'guest_name': forms.TextInput(attrs={'class': 'input'}),
            'guest_email': forms.EmailInput(attrs={'class': 'input'}),
            'issue_date': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
            'subtotal': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'tax_amount': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'total': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'amount_paid': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            'booking', 'invoice', 'amount', 'method',
            'reference', 'payment_date', 'notes',
        ]
        widgets = {
            'booking': forms.Select(attrs={'class': 'input'}),
            'invoice': forms.Select(attrs={'class': 'input'}),
            'amount': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'method': forms.Select(attrs={'class': 'input'}),
            'reference': forms.TextInput(attrs={'class': 'input'}),
            'payment_date': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount') or 0
        if amount <= 0:
            raise ValidationError('Payment amount must be positive.')
        return amount


# ---------------------------------------------------------------------------
#  Staff / Reviews
# ---------------------------------------------------------------------------
class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = [
            'user', 'property', 'full_name', 'email', 'phone', 'role',
            'salary', 'hire_date', 'is_active', 'notes',
        ]
        widgets = {
            'user': forms.Select(attrs={'class': 'input'}),
            'property': forms.Select(attrs={'class': 'input'}),
            'full_name': forms.TextInput(attrs={'class': 'input'}),
            'email': forms.EmailInput(attrs={'class': 'input'}),
            'phone': forms.TextInput(attrs={'class': 'input'}),
            'role': forms.Select(attrs={'class': 'input'}),
            'salary': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'hire_date': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = [
            'property', 'booking', 'guest_name', 'rating',
            'comment', 'source', 'review_date',
        ]
        widgets = {
            'property': forms.Select(attrs={'class': 'input'}),
            'booking': forms.Select(attrs={'class': 'input'}),
            'guest_name': forms.TextInput(attrs={'class': 'input'}),
            'rating': forms.NumberInput(attrs={'class': 'input', 'min': 1, 'max': 5}),
            'comment': forms.Textarea(attrs={'rows': 3, 'class': 'input'}),
            'source': forms.Select(attrs={'class': 'input'}),
            'review_date': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
        }

    def clean_rating(self):
        r = self.cleaned_data.get('rating') or 5
        if not (1 <= r <= 5):
            raise ValidationError('Rating must be between 1 and 5.')
        return r