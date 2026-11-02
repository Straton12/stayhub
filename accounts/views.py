# accounts/views.py
from django.conf import settings as dj_settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordResetView, PasswordResetDoneView,
    PasswordResetConfirmView, PasswordResetCompleteView,
)
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from .forms import (
    LoginForm, OrganizationForm, OrgAdminForm, GuestSignupForm,
    OrgAdminEditForm, OrgStaffCreateForm,
)
from .models import Organization, OrganizationMembership, User


# ===========================================================================
# ROLE HELPERS
# Defined FIRST so any view below can use them without an "undefined" error.
# ===========================================================================
def _is_superadmin(user):
    """
    True if the user is a platform-level super admin.
    Accepts either the Django is_superuser flag OR role='superadmin'.
    """
    if not user or not user.is_authenticated:
        return False
    return bool(
        getattr(user, 'is_superuser', False)
        or getattr(user, 'role', '') == 'superadmin'
    )


def _is_org_admin(user):
    """
    True for org-level admins and staff.
    Uses role in ('orgadmin', 'staff') OR the is_org_member property.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'role', '') in ('orgadmin', 'staff'):
        return True
    return bool(getattr(user, 'is_org_member', False))


def _is_guest(user):
    """
    True ONLY for guests — never for superadmin or org members.
    This is the crucial guard: a superuser with role='guest' is still
    a superadmin, not a guest.
    """
    if not user or not user.is_authenticated:
        return False
    if _is_superadmin(user) or _is_org_admin(user):
        return False
    return getattr(user, 'role', '') == 'guest'


# ===========================================================================
# OTHER HELPERS
# ===========================================================================
def _safe_next(request, default=''):
    """
    Return ?next (GET or POST) only if it's a local path.
    Rejects protocol-relative URLs ('//evil.com') and anything with a newline.
    """
    nxt = (request.GET.get('next') or request.POST.get('next') or '').strip()
    if nxt.startswith('/') and not nxt.startswith('//') and '\n' not in nxt:
        return nxt
    return default


def _guest_home_url():
    return getattr(dj_settings, 'GUEST_HOME_URL', '/my/')


def _redirect_after_login(request, user, honor_next=True):
    """
    Decide where a user goes after login.

    Priority:
      1. honor_next + safe ?next= → send there.
      2. Superadmin → /dashboard/
      3. Org member  → /dashboard/
      4. Guest       → /my/
      5. Fallback    → /dashboard/
    """
    if honor_next:
        nxt = _safe_next(request, '')
        if nxt:
            return redirect(nxt)

    if _is_superadmin(user):
        return redirect('dashboard')
    if _is_org_admin(user):
        return redirect('dashboard')
    if _is_guest(user):
        return redirect(_guest_home_url())
    return redirect('dashboard')


def _notify_welcome(user):
    """Best-effort welcome email/SMS — never blocks signup."""
    try:
        from notifications.services import on_guest_welcome
        on_guest_welcome(user)
    except Exception:
        pass


# ===========================================================================
# AUTH — login / logout
# ===========================================================================
def login_view(request):
    if request.user.is_authenticated:
        return _redirect_after_login(request, request.user, honor_next=True)

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Welcome back, {user.display_name}!')
            return _redirect_after_login(request, user, honor_next=True)
        messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {
        'form': form,
        'next': _safe_next(request, ''),
    })


def logout_view(request):
    logout(request)
    return redirect('marketplace:home')


# ===========================================================================
# GUEST SELF-REGISTRATION
# ===========================================================================
def guest_register(request):
    """
    Public guest self-signup.
      - Already logged in → route them home
      - ALLOW_GUEST_SIGNUP=False → bounce to login
      - On POST: create user, log them in, welcome email, redirect
    """
    if request.user.is_authenticated:
        return _redirect_after_login(request, request.user, honor_next=False)

    if not getattr(dj_settings, 'ALLOW_GUEST_SIGNUP', True):
        messages.info(request, 'Guest signup is currently disabled.')
        return redirect('login')

    next_url = _safe_next(request, '')

    if request.method == 'POST':
        form = GuestSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            _notify_welcome(user)

            first_name = (user.display_name or user.username).split()[0]
            messages.success(request, f'Welcome to StayHub, {first_name}!')

            return redirect(next_url or _guest_home_url())
    else:
        form = GuestSignupForm()

    return render(request, 'accounts/register.html', {
        'form': form,
        'next': next_url,
    })


# ===========================================================================
# DASHBOARD — smart landing by role
# ===========================================================================
@login_required
def dashboard(request):
    """
    - Guest          → /my/
    - Superadmin     → platform overview
    - Org admin/staff→ org dashboard
    """
    user = request.user

    # 1. Guests never belong here.
    if _is_guest(user):
        return redirect(_guest_home_url())

    # 2. Superadmin → platform overview.
    if _is_superadmin(user):
        orgs = Organization.objects.all().order_by('-created_at')
        return render(request, 'accounts/dashboard_superadmin.html', {
            'role':           'superadmin',
            'orgs':           orgs,
            'org_count':      orgs.count(),
            'user_count':     User.objects.count(),
            'active_count':   orgs.filter(is_active=True).count(),
            'network_count':  orgs.filter(network_joined=True).count(),
            'guest_count':    User.objects.filter(role='guest').count(),
            'staff_count':    User.objects.filter(role__in=['orgadmin', 'staff']).count(),
        })

    # 3. Org member → their org dashboard.
    org = getattr(user, 'organization', None)
    if org is None:
        messages.warning(request, 'Your account is not linked to an organization yet.')
        return render(request, 'accounts/dashboard_no_org.html', {
            'role': getattr(user, 'role', ''),
        })

    stats = _org_quick_stats(org)
    return render(request, 'accounts/dashboard.html', {
        'role':         user.role,
        'organization': org,
        'org_type':     org.org_type,
        'stats':        stats,
    })


def _org_quick_stats(org):
    """Safe cross-app counters for the org dashboard."""
    if org is None:
        return {}
    out = {}

    try:
        from marketplace.models import Listing
        out['listings_total']   = Listing.objects.filter(organization=org).count()
        out['listings_public']  = Listing.objects.filter(
            organization=org, status='approved', is_active=True,
        ).count()
        out['listings_pending'] = Listing.objects.filter(
            organization=org, status='pending',
        ).count()
    except Exception:
        pass

    try:
        from guestaccount.models import GuestBooking
        out['bookings_total']   = GuestBooking.objects.filter(organization=org).count()
        out['bookings_pending'] = GuestBooking.objects.filter(
            organization=org, status='pending',
        ).count()
        out['bookings_today']   = GuestBooking.objects.filter(
            organization=org, created_at__date=timezone.now().date(),
        ).count()
    except Exception:
        pass

    try:
        from marketplace.models import Review
        out['reviews_total'] = Review.objects.filter(
            listing__organization=org, is_published=True,
        ).count()
    except Exception:
        pass

    try:
        from notifications.models import NotificationLog
        out['notifications_unread'] = NotificationLog.objects.filter(
            recipient_organization=org,
            channel='inapp',
            read_at__isnull=True,
        ).count()
    except Exception:
        pass

    return out


# ===========================================================================
# SUPERADMIN — organizations
# ===========================================================================
@login_required
def superadmin_orgs(request):
    if not _is_superadmin(request.user):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    q = (request.GET.get('q') or '').strip()
    orgs = Organization.objects.all().order_by('-created_at')
    if q:
        orgs = orgs.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(location__icontains=q)
        )
    orgs = orgs.annotate(member_count=Count('members'))

    return render(request, 'accounts/superadmin_orgs.html', {
        'orgs': orgs,
        'q':    q,
    })


@login_required
def superadmin_create_org(request):
    """
    Create an Organization + its first org admin, safely handling the
    circular `owner` <-> `organization` reference between the two models.
    """
    if not _is_superadmin(request.user):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    if request.method == 'POST':
        org_form = OrganizationForm(request.POST, request.FILES)
        admin_form = OrgAdminForm(request.POST)

        if org_form.is_valid() and admin_form.is_valid():
            with transaction.atomic():
                # 1. Save the admin user first (no org yet).
                admin = admin_form.save(commit=False)
                admin.role = 'orgadmin'
                admin.is_staff = True
                admin.save()

                # 2. Save the org, pointing at the now-persisted admin.
                org = org_form.save(commit=False)
                org.owner = admin
                org.save()

                # 3. Link the admin to the org.
                admin.organization = org
                admin.save(update_fields=['organization'])

                # 4. Mirror the membership row.
                OrganizationMembership.objects.get_or_create(
                    user=admin,
                    organization=org,
                    defaults={'role': 'owner'},
                )

            messages.success(
                request,
                f'Organization "{org.name}" created with admin "{admin.username}".',
            )
            return redirect('superadmin_orgs')
    else:
        org_form = OrganizationForm()
        admin_form = OrgAdminForm()

    return render(request, 'accounts/superadmin_create_org.html', {
        'org_form':   org_form,
        'admin_form': admin_form,
    })


@login_required
def superadmin_toggle_org(request, org_id):
    if not _is_superadmin(request.user):
        return redirect('dashboard')

    org = get_object_or_404(Organization, id=org_id)
    org.is_active = not org.is_active
    org.save(update_fields=['is_active', 'updated_at'])
    messages.success(
        request,
        f'{org.name} is now {"active" if org.is_active else "inactive"}.',
    )
    return redirect('superadmin_orgs')


@login_required
def superadmin_org_detail(request, org_id):
    if not _is_superadmin(request.user):
        return redirect('dashboard')

    org = get_object_or_404(Organization, id=org_id)
    staff = org.members.all().order_by('role', 'username')
    memberships = org.memberships.select_related('user').all()
    stats = _org_quick_stats(org)

    return render(request, 'accounts/superadmin_org_detail.html', {
        'org':         org,
        'staff':       staff,
        'memberships': memberships,
        'stats':       stats,
    })


# ===========================================================================
# ORG ADMIN — staff management
# ===========================================================================
@login_required
def org_staff_list(request):
    if not (_is_org_admin(request.user) or _is_superadmin(request.user)):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    org = getattr(request.user, 'organization', None)
    if org is None:
        messages.warning(request, 'No organization linked to your account.')
        return redirect('dashboard')

    staff = User.objects.filter(organization=org).order_by('role', 'username')
    return render(request, 'accounts/org_staff_list.html', {
        'organization': org,
        'staff':        staff,
    })


@login_required
def org_staff_create(request):
    if not (_is_org_admin(request.user) or _is_superadmin(request.user)):
        messages.error(request, 'Only organization admins can add staff.')
        return redirect('dashboard')

    org = getattr(request.user, 'organization', None)
    if org is None:
        messages.warning(request, 'No organization linked to your account.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = OrgStaffCreateForm(request.POST)
        if form.is_valid():
            staff = form.save(commit=False)
            staff.role = 'staff'
            staff.organization = org
            staff.save()
            OrganizationMembership.objects.get_or_create(
                user=staff, organization=org,
                defaults={'role': 'staff'},
            )
            messages.success(request, f'Staff "{staff.username}" added.')
            return redirect('org_staff_list')
    else:
        form = OrgStaffCreateForm()

    return render(request, 'accounts/org_staff_create.html', {
        'form':         form,
        'organization': org,
    })


@login_required
def org_staff_edit(request, user_id):
    if not (_is_org_admin(request.user) or _is_superadmin(request.user)):
        messages.error(request, 'Access denied.')
        return redirect('dashboard')

    org = getattr(request.user, 'organization', None)
    staff = get_object_or_404(User, id=user_id, organization=org)

    if request.method == 'POST':
        form = OrgAdminEditForm(request.POST, instance=staff)
        if form.is_valid():
            form.save()
            messages.success(request, f'{staff.username} updated.')
            return redirect('org_staff_list')
    else:
        form = OrgAdminEditForm(instance=staff)

    return render(request, 'accounts/org_staff_edit.html', {
        'form':  form,
        'staff': staff,
    })


@login_required
def org_staff_toggle(request, user_id):
    if not (_is_org_admin(request.user) or _is_superadmin(request.user)):
        return redirect('dashboard')

    org = getattr(request.user, 'organization', None)
    staff = get_object_or_404(User, id=user_id, organization=org)
    staff.is_active = not staff.is_active
    staff.save(update_fields=['is_active'])
    messages.success(
        request,
        f'{staff.username} is now {"active" if staff.is_active else "disabled"}.',
    )
    return redirect('org_staff_list')


# ===========================================================================
# PASSWORD RESET
# ===========================================================================
class StayHubPasswordResetView(PasswordResetView):
    template_name = 'accounts/password_reset.html'
    email_template_name = 'accounts/password_reset_email.html'
    subject_template_name = 'accounts/password_reset_subject.txt'
    success_url = reverse_lazy('password_reset_done')


class StayHubPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'


class StayHubPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')


class StayHubPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'