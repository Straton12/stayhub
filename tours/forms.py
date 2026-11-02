# tours/forms.py
from django import forms
from django.core.exceptions import ValidationError

from .models import Guide, TourBooking, TourPackage, Vehicle


class TourPackageForm(forms.ModelForm):
    class Meta:
        model = TourPackage
        fields = [
            'name', 'package_type', 'destination', 'duration_days',
            'price_per_person', 'short_description', 'description',
            'cover_image_url', 'highlights', 'what_to_bring',
            'min_travellers', 'max_travellers', 'pickup_available',
            'languages', 'payment_policy', 'deposit_percent',
            'service_fee_percent', 'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'destination': forms.TextInput(attrs={'class': 'input'}),
            'short_description': forms.TextInput(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'class': 'input', 'rows': 5}),
            'highlights': forms.Textarea(attrs={'class': 'input', 'rows': 4,
                'placeholder': 'One per line, e.g.\nGame drive\nLunch included'}),
            'what_to_bring': forms.Textarea(attrs={'class': 'input', 'rows': 3,
                'placeholder': 'One per line, e.g.\nSunscreen\nBinoculars'}),
            'cover_image_url': forms.URLInput(attrs={'class': 'input'}),
            'languages': forms.TextInput(attrs={'class': 'input',
                'placeholder': 'English, Swahili'}),
        }

    def clean_price_per_person(self):
        v = self.cleaned_data.get('price_per_person') or 0
        if v < 0:
            raise ValidationError('Price cannot be negative.')
        return v

    def clean(self):
        cleaned = super().clean()
        min_t = cleaned.get('min_travellers') or 1
        max_t = cleaned.get('max_travellers') or 20
        if max_t < min_t:
            self.add_error('max_travellers',
                           'Max travellers must be ≥ min travellers.')
        if cleaned.get('payment_policy') == 'pay_deposit':
            pct = cleaned.get('deposit_percent') or 0
            if pct < 1 or pct > 100:
                self.add_error('deposit_percent',
                               'Deposit percent must be between 1 and 100.')
        return cleaned


class TourBookingForm(forms.ModelForm):
    class Meta:
        model = TourBooking
        fields = [
            'package', 'customer_name', 'customer_email', 'customer_phone',
            'travellers_count', 'travel_date', 'total_amount', 'amount_paid',
            'notes', 'special_requests',
        ]
        widgets = {
            'customer_name': forms.TextInput(attrs={'class': 'input'}),
            'customer_email': forms.EmailInput(attrs={'class': 'input'}),
            'customer_phone': forms.TextInput(attrs={'class': 'input'}),
            'travel_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 2}),
            'special_requests': forms.Textarea(attrs={'class': 'input', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        org = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        if org:
            self.fields['package'].queryset = TourPackage.objects.filter(
                organization=org, is_active=True,
            )

    def clean(self):
        cleaned = super().clean()
        total = cleaned.get('total_amount') or 0
        paid = cleaned.get('amount_paid') or 0
        if paid > total and total > 0:
            self.add_error('amount_paid', 'Amount paid cannot exceed total.')
        return cleaned


class GuideForm(forms.ModelForm):
    class Meta:
        model = Guide
        fields = ['name', 'phone', 'email', 'languages',
                  'license_number', 'is_active', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'phone': forms.TextInput(attrs={'class': 'input'}),
            'email': forms.EmailInput(attrs={'class': 'input'}),
            'languages': forms.TextInput(attrs={'class': 'input'}),
            'license_number': forms.TextInput(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 2}),
        }


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['name', 'plate_number', 'capacity',
                  'vehicle_type', 'is_active', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'plate_number': forms.TextInput(attrs={'class': 'input'}),
            'capacity': forms.NumberInput(attrs={'class': 'input', 'min': 1}),
            'vehicle_type': forms.TextInput(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 2}),
        }