# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify


class Organization(models.Model):
    ORG_TYPES = [
        ('bnb',        'BnB / Stays'),
        ('tours',      'Tours & Travel'),
        ('restaurant', 'Restaurant'),
        ('laundry',    'Laundry'),
        ('network',    'Network / Referrals'),
        ('mixed',      'Mixed Services'),
    ]

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    org_type = models.CharField(max_length=20, choices=ORG_TYPES, default='bnb')
    owner = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='owned_organizations',
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    location = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=300, blank=True)
    logo = models.ImageField(upload_to='orgs/logos/', blank=True, null=True)

    is_active = models.BooleanField(default=True)
    network_joined = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'org'
            s, n = base, 2
            while Organization.objects.filter(slug=s).exclude(pk=self.pk).exists():
                s = f"{base}-{n}"; n += 1
            self.slug = s
        super().save(*args, **kwargs)


class User(AbstractUser):
    ROLES = [
        ('superadmin', 'Super Admin'),
        ('orgadmin',   'Organization Admin'),
        ('staff',      'Staff'),
        ('guest',      'Guest'),
    ]

    role = models.CharField(max_length=20, choices=ROLES, default='guest')
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    organization = models.ForeignKey(
        'accounts.Organization',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='members',
    )

    @property
    def display_name(self):
        return self.full_name or self.get_full_name() or self.username

    # The single source of truth for role checks ---------------------------
    @property
    def is_superadmin(self):
        # is_superuser is the strongest signal — never overridden by role.
        return bool(self.is_superuser or self.role == 'superadmin')

    @property
    def is_org_admin(self):
        return self.role == 'orgadmin'

    @property
    def is_org_member(self):
        return self.role in ('orgadmin', 'staff') and self.organization_id is not None

    @property
    def is_guest(self):
        # Guests are ONLY users who are neither superadmins nor org members.
        if self.is_superuser or self.role in ('superadmin', 'orgadmin', 'staff'):
            return False
        return self.role == 'guest'

    def __str__(self):
        return self.display_name


class OrganizationMembership(models.Model):
    ROLES = [
        ('owner',   'Owner'),
        ('admin',   'Admin'),
        ('manager', 'Manager'),
        ('staff',   'Staff'),
        ('viewer',  'Viewer'),
    ]
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='organization_memberships',
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(max_length=20, choices=ROLES, default='staff')
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'organization')
        ordering = ['organization', 'user']

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"