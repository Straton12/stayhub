# marketplace/forms.py
from django import forms
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet

from .models import Listing, ListingCategory, ListingImage, MAX_GALLERY_IMAGES


# ---------------------------------------------------------------------------
# Listing form
# ---------------------------------------------------------------------------
class ListingForm(forms.ModelForm):
    amenities = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': 'One per line, e.g.\nWiFi\nAir conditioning\nFree parking\nPool access',
            'class': 'input',
        }),
    )
    house_rules = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': 'One per line, e.g.\nNo smoking\nNo pets\nQuiet hours 22:00–07:00',
            'class': 'input',
        }),
    )

    class Meta:
        model = Listing
        fields = [
            # Identity
            'title', 'category',
            'short_description', 'description',
            # Location
            'location', 'address', 'latitude', 'longitude',
            # Commercial
            'price', 'price_unit', 'min_nights', 'max_guests',
            'bedrooms', 'beds', 'baths',
            # Rules
            'amenities', 'house_rules',
            'check_in_time', 'check_out_time', 'cancellation_policy',
            # Payment
            'payment_policy', 'deposit_percent', 'service_fee_percent',
            # Cover image
            'cover_image', 'cover_image_url',
            # Contact
            'contact_phone', 'contact_email', 'whatsapp',
            # Socials
            'website', 'facebook', 'instagram', 'twitter', 'tiktok', 'youtube',
            # Toggles
            'accepts_bookings', 'pay_first',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'e.g. Westlands Skyline Apartments — Room 2B',
            }),
            'short_description': forms.TextInput(attrs={
                'class': 'input',
                'placeholder': 'One-line summary (max 280 chars)',
            }),
            'description': forms.Textarea(attrs={
                'class': 'input', 'rows': 6,
                'placeholder': 'Describe what makes this listing special…',
            }),
            'location': forms.TextInput(attrs={
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
            'price': forms.NumberInput(attrs={
                'class': 'input', 'min': 0, 'step': '0.01',
            }),
            'price_unit': forms.TextInput(attrs={
                'class': 'input', 'placeholder': 'per night',
            }),
            'check_in_time': forms.TextInput(attrs={
                'class': 'input', 'placeholder': '14:00',
            }),
            'check_out_time': forms.TextInput(attrs={
                'class': 'input', 'placeholder': '10:00',
            }),
            'cover_image_url': forms.URLInput(attrs={
                'class': 'input', 'placeholder': 'https://… (optional)',
            }),
            # Contact
            'contact_phone': forms.TextInput(attrs={
                'class': 'input', 'placeholder': '+254 712 345 678',
            }),
            'contact_email': forms.EmailInput(attrs={
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
        }

    # ---- Validation -------------------------------------------------------
    def clean_title(self):
        title = (self.cleaned_data.get('title') or '').strip()
        if len(title) < 4:
            raise forms.ValidationError('Please enter a title of at least 4 characters.')
        return title

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price < 0:
            raise forms.ValidationError('Price cannot be negative.')
        return price

    def clean_service_fee_percent(self):
        v = self.cleaned_data.get('service_fee_percent')
        if v is None:
            return 5
        if v < 0 or v > 50:
            raise forms.ValidationError('Service fee must be between 0 and 50 percent.')
        return v

    def clean_deposit_percent(self):
        v = self.cleaned_data.get('deposit_percent') or 0
        if v < 0 or v > 100:
            raise forms.ValidationError('Deposit percent must be 0–100.')
        return v

    def clean_whatsapp(self):
        v = (self.cleaned_data.get('whatsapp') or '').strip()
        if v and not any(ch.isdigit() for ch in v):
            raise forms.ValidationError('WhatsApp number must contain digits.')
        return v

    def clean(self):
        cleaned = super().clean()
        # Require at least one image source for new listings
        if not self.instance.pk:
            has_file = bool(cleaned.get('cover_image'))
            has_url = bool((cleaned.get('cover_image_url') or '').strip())
            if not has_file and not has_url:
                raise forms.ValidationError(
                    'Please upload a cover image or provide a cover image URL.'
                )
        return cleaned


# ---------------------------------------------------------------------------
# Gallery image form
# ---------------------------------------------------------------------------
class ListingImageForm(forms.ModelForm):
    class Meta:
        model = ListingImage
        fields = ['image', 'image_url', 'caption', 'display_order']
        widgets = {
            'image_url': forms.URLInput(attrs={
                'class': 'input', 'placeholder': 'https://…',
            }),
            'caption': forms.TextInput(attrs={
                'class': 'input', 'placeholder': 'Optional caption',
            }),
        }

    def clean_display_order(self):
        val = self.cleaned_data.get('display_order')
        return val if val is not None else 10


# ---------------------------------------------------------------------------
# Category form
# ---------------------------------------------------------------------------
class ListingCategoryForm(forms.ModelForm):
    ICON_CHOICES = [
        ('bed',      'Bed — for stays'),
        ('globe',    'Globe — for tours and travel'),
        ('utensils', 'Utensils — for restaurants and food'),
        ('shirt',    'Shirt — for laundry'),
        ('car',      'Car — for transport'),
        ('grid',     'Grid — generic'),
    ]
    ACCENT_CHOICES = [
        ('sky',     'Sky blue'),
        ('emerald', 'Emerald green'),
        ('amber',   'Amber orange'),
        ('violet',  'Violet'),
        ('indigo',  'Indigo (default)'),
        ('rose',    'Rose pink'),
    ]

    class Meta:
        model = ListingCategory
        fields = ['name', 'slug', 'description', 'icon', 'accent', 'display_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'e.g. Stays'}),
            'slug': forms.TextInput(attrs={
                'class': 'input', 'placeholder': 'e.g. stays (lowercase, no spaces)',
            }),
            'description': forms.TextInput(attrs={
                'class': 'input', 'placeholder': 'e.g. Homes, apartments and hotels',
            }),
            'display_order': forms.NumberInput(attrs={'class': 'input', 'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['icon'] = forms.ChoiceField(
            choices=self.ICON_CHOICES, initial='grid',
            widget=forms.Select(attrs={'class': 'input'}),
        )
        self.fields['accent'] = forms.ChoiceField(
            choices=self.ACCENT_CHOICES, initial='indigo',
            widget=forms.Select(attrs={'class': 'input'}),
        )
        if not self.instance.pk:
            self.fields['display_order'].initial = 10

    def clean_slug(self):
        slug = (self.cleaned_data.get('slug') or '').strip().lower()
        if not slug:
            raise forms.ValidationError('Please enter a short slug (letters, digits, dashes).')
        return slug


# ---------------------------------------------------------------------------
# Gallery formset — enforces the 4-image cap
# ---------------------------------------------------------------------------
class BaseListingImageFormSet(BaseInlineFormSet):
    """
    Treat a form as 'empty' (skippable) when it has neither an image file
    nor an image URL — even if a caption was typed.
    """

    def _should_delete_form(self, form):
        if form.cleaned_data.get('DELETE', False):
            return True

        image = form.cleaned_data.get('image')
        url = (form.cleaned_data.get('image_url') or '').strip()

        if not image and not url:
            if form.instance.pk:
                has_existing_image = bool(form.instance.image)
                has_existing_url = bool((form.instance.image_url or '').strip())
                if has_existing_image or has_existing_url:
                    return False
            return True

        return False

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = 0
        for form in self.forms:
            if not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE', False):
                continue
            image = form.cleaned_data.get('image')
            url = (form.cleaned_data.get('image_url') or '').strip()
            if image or url:
                kept += 1
        if kept > MAX_GALLERY_IMAGES:
            raise forms.ValidationError(
                f'Please provide at most {MAX_GALLERY_IMAGES} gallery images.'
            )


ListingImageFormSet = inlineformset_factory(
    Listing,
    ListingImage,
    form=ListingImageForm,
    formset=BaseListingImageFormSet,
    extra=MAX_GALLERY_IMAGES,
    can_delete=True,
    max_num=MAX_GALLERY_IMAGES,
    validate_max=True,
)