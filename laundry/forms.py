# laundry/forms.py
from django import forms
from django.core.exceptions import ValidationError

from .models import LaundryService, LaundryOrder, LaundrySupply


class LaundryServiceForm(forms.ModelForm):
    class Meta:
        model = LaundryService
        fields = [
            'name', 'service_type', 'price', 'price_unit',
            'short_description', 'description', 'cover_image_url',
            'turnaround_hours', 'pickup_available', 'delivery_available',
            'same_day', 'payment_policy', 'service_fee_percent', 'is_active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'input'}),
            'short_description': forms.TextInput(attrs={'class': 'input'}),
            'name': forms.TextInput(attrs={'class': 'input'}),
        }

    def clean_price(self):
        p = self.cleaned_data.get('price') or 0
        if p < 0:
            raise ValidationError('Price cannot be negative.')
        return p


class LaundryOrderForm(forms.ModelForm):
    class Meta:
        model = LaundryOrder
        fields = [
            'service', 'customer_name', 'customer_phone',
            'pickup_address', 'delivery_address',
            'item_description', 'quantity', 'unit_price',
            'total_amount', 'amount_paid', 'payment_policy', 'notes',
        ]
        widgets = {
            'item_description': forms.Textarea(attrs={'rows': 3, 'class': 'input'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
            'customer_name': forms.TextInput(attrs={'class': 'input'}),
        }

    def __init__(self, *args, **kwargs):
        org = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        if org:
            self.fields['service'].queryset = LaundryService.objects.filter(
                organization=org, is_active=True,
            )

    def clean(self):
        cleaned = super().clean()
        total = cleaned.get('total_amount') or 0
        paid = cleaned.get('amount_paid') or 0
        if paid > total and total > 0:
            self.add_error('amount_paid', 'Amount paid cannot exceed total.')
        return cleaned


class LaundrySupplyForm(forms.ModelForm):
    class Meta:
        model = LaundrySupply
        fields = ['name', 'quantity', 'unit', 'reorder_level', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'input'}),
        }