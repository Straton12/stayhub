# accounts/forms.py
from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError

from .models import User, Organization


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Username or email',
        'class': 'input',
        'autocomplete': 'username',
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Password',
        'class': 'input',
        'autocomplete': 'current-password',
    }))


# ---------------------------------------------------------------------------
# Organization (superadmin)
# ---------------------------------------------------------------------------
class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name', 'org_type', 'email', 'phone', 'location', 'address', 'logo']
        widgets = {
            'name':     forms.TextInput(attrs={'class': 'input', 'placeholder': 'Organization name'}),
            'org_type': forms.Select(attrs={'class': 'input'}),
            'email':    forms.EmailInput(attrs={'class': 'input', 'placeholder': 'Email'}),
            'phone':    forms.TextInput(attrs={'class': 'input', 'placeholder': 'Phone'}),
            'location': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Location'}),
            'address':  forms.TextInput(attrs={'class': 'input', 'placeholder': 'Address'}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        qs = Organization.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('An organization with this name already exists.')
        return name


class OrgAdminForm(UserCreationForm):
    """Creates the first admin user for a new organization."""
    class Meta:
        model = User
        fields = ['username', 'email', 'phone', 'full_name', 'password1', 'password2']
        widgets = {
            'username':  forms.TextInput(attrs={'class': 'input', 'placeholder': 'Username'}),
            'email':     forms.EmailInput(attrs={'class': 'input', 'placeholder': 'Email'}),
            'phone':     forms.TextInput(attrs={'class': 'input', 'placeholder': 'Phone'}),
            'full_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Full name'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({
            'class': 'input', 'placeholder': 'Password',
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'input', 'placeholder': 'Confirm password',
        })

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError('A user with this email already exists.')
        return email


class OrgStaffCreateForm(UserCreationForm):
    """Org admin creates a staff user under their organization."""
    class Meta:
        model = User
        fields = ['username', 'email', 'phone', 'full_name', 'password1', 'password2']
        widgets = {
            'username':  forms.TextInput(attrs={'class': 'input', 'placeholder': 'Username'}),
            'email':     forms.EmailInput(attrs={'class': 'input', 'placeholder': 'Email'}),
            'phone':     forms.TextInput(attrs={'class': 'input', 'placeholder': 'Phone'}),
            'full_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Full name'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({'class': 'input', 'placeholder': 'Password'})
        self.fields['password2'].widget.attrs.update({'class': 'input', 'placeholder': 'Confirm password'})

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError('A user with this email already exists.')
        return email


class OrgAdminEditForm(forms.ModelForm):
    """Edit an existing staff user (no password change)."""
    class Meta:
        model = User
        fields = ['full_name', 'email', 'phone', 'is_active']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Full name'}),
            'email':     forms.EmailInput(attrs={'class': 'input', 'placeholder': 'Email'}),
            'phone':     forms.TextInput(attrs={'class': 'input', 'placeholder': 'Phone'}),
        }


# ---------------------------------------------------------------------------
# Guest self-signup
# ---------------------------------------------------------------------------
class GuestSignupForm(forms.Form):
    """
    Guest self-registration form.
    Creates a User with role='guest' and username = email.
    """
    full_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'input',
            'placeholder': 'e.g. Jane Mwangi',
            'autocomplete': 'name',
        }),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'input',
            'placeholder': 'you@example.com',
            'autocomplete': 'email',
        }),
    )
    phone = forms.CharField(
        max_length=30, required=False,
        widget=forms.TextInput(attrs={
            'class': 'input',
            'placeholder': '+254 7XX XXX XXX',
            'autocomplete': 'tel',
        }),
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'input',
            'placeholder': 'Choose a strong password',
            'autocomplete': 'new-password',
        }),
    )
    password2 = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(attrs={
            'class': 'input',
            'placeholder': 'Type it again',
            'autocomplete': 'new-password',
        }),
    )

    def clean_full_name(self):
        name = (self.cleaned_data.get('full_name') or '').strip()
        if len(name) < 2:
            raise ValidationError('Please enter your full name.')
        return name

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        if User.objects.filter(username__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'The two passwords do not match.')
        if p1:
            try:
                password_validation.validate_password(p1)
            except ValidationError as e:
                self.add_error('password1', e)
        return cleaned

    def save(self):
        data = self.cleaned_data
        user = User.objects.create_user(
            username=data['email'],           # username = email
            email=data['email'],
            password=data['password1'],
            role='guest',
            full_name=data['full_name'],
            phone=data.get('phone', ''),
        )
        # Best-effort guest profile
        try:
            from guestaccount.models import GuestProfile
            GuestProfile.objects.get_or_create(user=user)
        except Exception:
            pass
        return user