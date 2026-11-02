# notifications/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import NotificationLog


# ============================================================
# INBOX
# ============================================================
@login_required
def inbox(request):
    """
    Show notifications for the current user.
    - Guest users see their own notifications.
    - Org members see the org's notifications plus their personal ones.
    """
    qs = NotificationLog.objects.all()

    if getattr(request.user, 'is_guest', False):
        qs = qs.filter(recipient_user=request.user)
    elif getattr(request.user, 'is_org_member', False) and request.user.organization_id:
        qs = qs.filter(
            recipient_organization=request.user.organization,
        ) | qs.filter(recipient_user=request.user)
    else:
        qs = qs.filter(recipient_user=request.user)

    qs = qs.order_by('-created_at')

    channel = request.GET.get('channel', '').strip()
    if channel:
        qs = qs.filter(channel=channel)

    unread = qs.filter(read_at__isnull=True).count()

    return render(request, 'notifications/inbox.html', {
        'notifications': qs[:200],
        'unread': unread,
        'channel': channel,
    })


@login_required
def mark_read(request, pk):
    log = get_object_or_404(NotificationLog, pk=pk)

    # Authorization
    if log.recipient_user_id and log.recipient_user_id != request.user.id \
            and not getattr(request.user, 'is_superadmin', False):
        messages.error(request, 'Not authorized.')
        return redirect('notifications:inbox')

    log.mark_read()
    return redirect('notifications:inbox')


@login_required
def mark_all_read(request):
    if request.method != 'POST':
        return redirect('notifications:inbox')

    if getattr(request.user, 'is_guest', False):
        NotificationLog.objects.filter(
            recipient_user=request.user, read_at__isnull=True,
        ).update(read_at=__import__('django.utils.timezone',
                                    fromlist=['now']).now())
    elif request.user.organization_id:
        NotificationLog.objects.filter(
            recipient_organization=request.user.organization,
            read_at__isnull=True,
        ).update(read_at=__import__('django.utils.timezone',
                                    fromlist=['now']).now())

    messages.success(request, 'All notifications marked as read.')
    return redirect('notifications:inbox')


@login_required
def detail(request, pk):
    log = get_object_or_404(NotificationLog, pk=pk)
    # Auto-mark read on open
    if not log.is_read:
        log.mark_read()
    return render(request, 'notifications/detail.html', {'notification': log})


# ============================================================
# API — unread count badge
# ============================================================
@login_required
def unread_count(request):
    qs = NotificationLog.objects.filter(read_at__isnull=True)
    if getattr(request.user, 'is_guest', False):
        qs = qs.filter(recipient_user=request.user)
    elif request.user.organization_id:
        qs = qs.filter(
            recipient_organization=request.user.organization,
        ) | qs.filter(recipient_user=request.user)
    else:
        qs = qs.filter(recipient_user=request.user)
    return JsonResponse({'unread': qs.distinct().count()})


# ============================================================
# HEALTH
# ============================================================
def health(request):
    from django.http import HttpResponse
    return HttpResponse('ok')