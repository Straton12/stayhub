# network/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Organization
from .models import NetworkProfile, Referral


# ============================================================
# HELPERS
# ============================================================
def _org(request):
    return getattr(request.user, 'organization', None)


def _require_org(request):
    org = _org(request)
    if not org:
        messages.error(request, 'No organization assigned.')
        return None
    if not getattr(request.user, 'is_org_member', False) and \
       not getattr(request.user, 'is_superadmin', False):
        messages.error(request, 'Only organization members can use the network.')
        return None
    return org


def _get_referral_for_org(referral_id, org):
    """Fetch a referral the org either sent or received."""
    return get_object_or_404(
        Referral,
        id=referral_id,
    ) if not org else get_object_or_404(
        Referral.objects.filter(models_q(from_org=org) | models_q(to_org=org)).distinct(),
        id=referral_id,
    )


# Tiny helper so we don't have to import Q at the top just for one function
def models_q(**kwargs):
    from django.db.models import Q
    return Q(**kwargs)


# ============================================================
# DASHBOARD
# ============================================================
@login_required
def network_dashboard(request):
    org = _require_org(request)
    if not org:
        return redirect('dashboard')

    sent = Referral.objects.filter(from_org=org).order_by('-created_at')
    received = Referral.objects.filter(to_org=org).order_by('-created_at')

    partners = (
        Organization.objects
        .filter(network_joined=True, is_active=True)
        .exclude(id=org.id)
        .order_by('name')
    )

    profile, _ = NetworkProfile.objects.get_or_create(organization=org)
    partner_listings = profile.partner_listings(limit=12)

    # Small KPI set
    kpis = {
        'sent_total':       sent.count(),
        'sent_open':        sent.filter(status__in=['pending', 'accepted']).count(),
        'received_total':   received.count(),
        'received_open':    received.filter(status__in=['pending', 'accepted']).count(),
        'commission_due':   sum(
            (r.commission_due for r in sent if not r.commission_paid and r.commission > 0),
            start=0,
        ),
        'commission_earned': sum(
            (r.commission for r in received if r.commission_paid),
            start=0,
        ),
    }

    return render(request, 'network/dashboard.html', {
        'sent': sent,
        'received': received,
        'partners': partners,
        'partner_listings': partner_listings,
        'joined': org.network_joined,
        'profile': profile,
        'kpis': kpis,
    })


# ============================================================
# JOIN / LEAVE
# ============================================================
@login_required
def toggle_network(request):
    org = _require_org(request)
    if not org:
        return redirect('dashboard')

    org.network_joined = not org.network_joined
    org.save(update_fields=['network_joined', 'updated_at'])

    if org.network_joined:
        NetworkProfile.objects.get_or_create(organization=org)
        messages.success(request, 'You have joined the network.')
    else:
        # Keep the profile (history) but mark the org as not joined
        messages.success(request, 'You have left the network.')

    return redirect('network_dashboard')


# ============================================================
# REFERRALS
# ============================================================
@login_required
def referral_create(request):
    org = _require_org(request)
    if not org:
        return redirect('dashboard')

    partners = (
        Organization.objects
        .filter(network_joined=True, is_active=True)
        .exclude(id=org.id)
        .order_by('name')
    )

    if request.method == 'POST':
        to_org_id = request.POST.get('to_org')
        to_org = Organization.objects.filter(id=to_org_id, network_joined=True).exclude(id=org.id).first()
        if not to_org:
            messages.error(request, 'Please pick a valid partner organization.')
        else:
            profile, _ = NetworkProfile.objects.get_or_create(organization=org)
            referral = Referral.objects.create(
                from_org=org,
                to_org=to_org,
                guest_name=request.POST.get('guest_name', '').strip(),
                guest_phone=request.POST.get('guest_phone', '').strip(),
                guest_email=request.POST.get('guest_email', '').strip(),
                service_needed=request.POST.get('service_needed', '').strip(),
                notes=request.POST.get('notes', '').strip(),
                value=request.POST.get('value') or 0,
                commission=request.POST.get('commission') or 0,
                commission_rate=profile.commission_rate or 0,
                source='manual',
            )
            # Notify the receiving org
            referral._notify(
                to_org,
                'network.referral.created',
                f'New referral {referral.reference} from {org.name}',
                body=f'{referral.guest_name} — {referral.service_needed}',
            )
            messages.success(request, 'Referral sent.')
            return redirect('network_dashboard')

    return render(request, 'network/referral_form.html', {
        'partners': partners,
        'profile': NetworkProfile.objects.get_or_create(organization=org)[0],
    })


@login_required
def referral_detail(request, referral_id):
    org = _require_org(request)
    if not org:
        return redirect('dashboard')

    referral = _get_referral_for_org(referral_id, org)
    return render(request, 'network/referral_detail.html', {
        'referral': referral,
        'is_sender': referral.from_org_id == org.id,
        'is_receiver': referral.to_org_id == org.id,
    })


@login_required
def referral_update(request, referral_id, status):
    org = _require_org(request)
    if not org:
        return redirect('dashboard')

    referral = _get_referral_for_org(referral_id, org)

    if referral.from_org_id != org.id and referral.to_org_id != org.id:
        messages.error(request, 'Not authorized.')
        return redirect('network_dashboard')

    if status not in dict(Referral.STATUS):
        messages.error(request, 'Invalid status.')
        return redirect('network_dashboard')

    # Lifecycle transitions use model methods so notifications fire
    if status == 'accepted':
        referral.mark_accepted()
    elif status == 'completed':
        referral.mark_completed()
    elif status == 'rejected':
        referral.mark_rejected()
    else:
        referral.status = status
        referral.save(update_fields=['status'])

    messages.success(request, f'Referral marked as {status}.')
    return redirect('network_dashboard')


@login_required
def referral_mark_paid(request, referral_id):
    org = _require_org(request)
    if not org:
        return redirect('dashboard')

    referral = get_object_or_404(Referral, id=referral_id)

    # Only the sender pays the receiver's commission
    if referral.from_org_id != org.id and not getattr(request.user, 'is_superadmin', False):
        messages.error(request, 'Not authorized.')
        return redirect('network_dashboard')

    referral.mark_paid()
    messages.success(request, 'Commission marked as paid.')
    return redirect('network_dashboard')


# ============================================================
# PROFILE
# ============================================================
@login_required
def profile_edit(request):
    org = _require_org(request)
    if not org:
        return redirect('dashboard')

    profile, _ = NetworkProfile.objects.get_or_create(organization=org)

    if request.method == 'POST':
        profile.tagline = request.POST.get('tagline', '').strip()
        profile.service_area = request.POST.get('service_area', '').strip()
        profile.offers_referrals = 'offers_referrals' in request.POST
        profile.accepts_referrals = 'accepts_referrals' in request.POST
        profile.visible_to_guests = 'visible_to_guests' in request.POST
        try:
            profile.commission_rate = request.POST.get('commission_rate') or 0
        except Exception:
            pass
        profile.categories = request.POST.get('categories', '').strip()
        profile.save()
        messages.success(request, 'Network profile updated.')
        return redirect('network_dashboard')

    return render(request, 'network/profile_form.html', {'profile': profile})