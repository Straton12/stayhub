# network/forms.py
from django import forms

from .models import NetworkProfile, Referral


class ReferralForm(forms.ModelForm):
    class Meta:
        model = Referral
        fields = [
            'to_org', 'guest_name', 'guest_phone', 'guest_email',
            'service_needed', 'notes', 'value', 'commission',
        ]
        widgets = {
            'guest_name': forms.TextInput(attrs={'class': 'input'}),
            'guest_phone': forms.TextInput(attrs={'class': 'input'}),
            'guest_email': forms.EmailInput(attrs={'class': 'input'}),
            'service_needed': forms.TextInput(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 3}),
            'value': forms.NumberInput(attrs={'class': 'input', 'min': 0, 'step': '0.01'}),
            'commission': forms.NumberInput(attrs={'class': 'input', 'min': 0, 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        org = kwargs.pop('organization', None)
        super().__init__(*args, **kwargs)
        if org:
            self.fields['to_org'].queryset = (
                self.fields['to_org'].queryset
                .filter(network_joined=True, is_active=True)
                .exclude(id=org.id)
            )

    def clean_value(self):
        v = self.cleaned_data.get('value') or 0
        if v < 0:
            raise forms.ValidationError('Value cannot be negative.')
        return v

    def clean_commission(self):
        c = self.cleaned_data.get('commission') or 0
        if c < 0:
            raise forms.ValidationError('Commission cannot be negative.')
        return c


class NetworkProfileForm(forms.ModelForm):
    class Meta:
        model = NetworkProfile
        fields = [
            'tagline', 'service_area',
            'offers_referrals', 'accepts_referrals', 'visible_to_guests',
            'commission_rate', 'categories',
        ]
        widgets = {
            'tagline': forms.TextInput(attrs={'class': 'input'}),
            'service_area': forms.TextInput(attrs={'class': 'input'}),
            'commission_rate': forms.NumberInput(attrs={'class': 'input',
                                                        'min': 0, 'max': 100, 'step': '0.01'}),
            'categories': forms.TextInput(attrs={'class': 'input',
                'placeholder': 'stays,tours,food'}),
        }

    def clean_commission_rate(self):
        r = self.cleaned_data.get('commission_rate') or 0
        if r < 0 or r > 100:
            raise forms.ValidationError('Commission rate must be 0–100.')
        return r