# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from .models import User, Organization, OrganizationMembership


# ---------------------------------------------------------------------------
# Organization membership inline
# ---------------------------------------------------------------------------
class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 0
    autocomplete_fields = ['user']
    fields = ('user', 'role', 'is_active', 'joined_at')
    readonly_fields = ('joined_at',)
    show_change_link = True


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------
@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'org_type', 'location', 'owner',
        'is_active', 'network_joined', 'member_count_display', 'created_at',
    )
    list_filter = ('org_type', 'is_active', 'network_joined')
    search_fields = ('name', 'email', 'location', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ['owner']
    readonly_fields = ('created_at', 'updated_at')
    inlines = [OrganizationMembershipInline]

    fieldsets = (
        ('Identity', {
            'fields': ('name', 'slug', 'org_type', 'logo'),
        }),
        ('Contact', {
            'fields': ('email', 'phone', 'location', 'address'),
        }),
        ('Ownership', {
            'fields': ('owner',),
        }),
        ('Status', {
            'fields': ('is_active', 'network_joined'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['make_active', 'make_inactive', 'join_network', 'leave_network']

    @admin.display(description='Members')
    def member_count_display(self, obj):
        return obj.members.count()

    @admin.action(description='Mark selected organizations as active')
    def make_active(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f'{n} organization(s) activated.')

    @admin.action(description='Mark selected organizations as inactive')
    def make_inactive(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f'{n} organization(s) deactivated.')

    @admin.action(description='Add selected organizations to the network')
    def join_network(self, request, queryset):
        n = queryset.update(network_joined=True)
        self.message_user(request, f'{n} organization(s) joined the network.')

    @admin.action(description='Remove selected organizations from the network')
    def leave_network(self, request, queryset):
        n = queryset.update(network_joined=False)
        self.message_user(request, f'{n} organization(s) left the network.')


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
@admin.register(User)
class CustomUserAdmin(DjangoUserAdmin):
    list_display = (
        'username', 'email', 'full_name', 'role',
        'organization', 'is_active', 'is_staff', 'date_joined',
    )
    list_filter = ('role', 'is_active', 'is_staff', 'is_superuser', 'organization')
    search_fields = ('username', 'email', 'full_name', 'phone')
    ordering = ('-date_joined',)
    autocomplete_fields = ['organization']
    readonly_fields = ('date_joined', 'last_login')

    fieldsets = DjangoUserAdmin.fieldsets + (
        ('StayHub Profile', {
            'fields': ('role', 'full_name', 'phone', 'organization'),
        }),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('StayHub Profile', {
            'fields': ('role', 'full_name', 'phone', 'organization'),
        }),
    )

    actions = ['make_guest', 'make_staff', 'make_org_admin', 'deactivate_users']

    @admin.display(description='Name')
    def display_name_col(self, obj):
        return obj.display_name

    @admin.action(description='Set role → guest')
    def make_guest(self, request, queryset):
        n = queryset.update(role='guest')
        self.message_user(request, f'{n} user(s) set to guest.')

    @admin.action(description='Set role → staff')
    def make_staff(self, request, queryset):
        n = queryset.update(role='staff')
        self.message_user(request, f'{n} user(s) set to staff.')

    @admin.action(description='Set role → org admin')
    def make_org_admin(self, request, queryset):
        n = queryset.update(role='orgadmin')
        self.message_user(request, f'{n} user(s) set to org admin.')

    @admin.action(description='Deactivate selected users')
    def deactivate_users(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f'{n} user(s) deactivated.')


# ---------------------------------------------------------------------------
# Membership (standalone, for filtering/searching)
# ---------------------------------------------------------------------------
@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'is_active', 'joined_at')
    list_filter = ('role', 'is_active', 'organization')
    search_fields = ('user__username', 'user__email', 'organization__name')
    autocomplete_fields = ['user', 'organization']
    readonly_fields = ('joined_at',)