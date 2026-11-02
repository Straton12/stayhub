# notifications/services.py
"""
The one place that actually sends things.

Two layers:
  1. Low-level senders: send_email(), send_sms(), send_inapp()
  2. Event hooks: on_* functions for each lifecycle event.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from .backends import get_sms_backend
from .models import NotificationLog, notify


# ============================================================
# LOW-LEVEL SENDERS
# ============================================================
def send_email(to_email, subject, body_text, body_html=None,
               event='', user=None, related='', kind='',
               recipient_organization=None, guest_booking=None,
               priority='normal'):
    log = NotificationLog.objects.create(
        channel='email', status='queued',
        recipient_user=user,
        recipient_organization=recipient_organization,
        to_email=to_email,
        subject=subject, body=body_text,
        event=event, kind=kind,
        related_object_repr=related,
        guest_booking=guest_booking,
        priority=priority,
    )

    if not to_email:
        log.mark_failed('No email address.')
        return log

    try:
        if body_html:
            msg = EmailMultiAlternatives(
                subject=subject, body=body_text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email],
            )
            msg.attach_alternative(body_html, 'text/html')
            msg.send(fail_silently=False)
        else:
            send_mail(
                subject=subject, message=body_text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[to_email],
                fail_silently=False,
            )
        log.mark_sent()
    except Exception as e:
        log.mark_failed(str(e))

    return log


def send_sms(to_phone, message, event='', user=None, related='',
             kind='', recipient_organization=None, guest_booking=None,
             priority='normal'):
    log = NotificationLog.objects.create(
        channel='sms', status='queued',
        recipient_user=user,
        recipient_organization=recipient_organization,
        to_phone=to_phone, body=message,
        event=event, kind=kind,
        related_object_repr=related,
        guest_booking=guest_booking,
        priority=priority,
    )

    if not to_phone:
        log.mark_failed('No phone number.')
        return log

    try:
        backend = get_sms_backend()
        ok, provider_id, error = backend.send(to_phone, message)
        if ok:
            log.mark_sent(provider_id)
        else:
            log.mark_failed(error)
    except Exception as e:
        log.mark_failed(str(e))

    return log


def send_inapp(*, subject, body='', recipient_user=None,
               recipient_organization=None, event='', kind='',
               guest_booking=None, related='', priority='normal'):
    """In-app notifications — always succeed synchronously."""
    return notify(
        event=event, kind=kind, subject=subject, body=body,
        recipient_user=recipient_user,
        recipient_organization=recipient_organization,
        guest_booking=guest_booking,
        channel='inapp', status='sent',
        priority=priority, related_object_repr=related,
    )


# ============================================================
# HELPERS
# ============================================================
def _frontend_url(path=''):
    host = 'localhost:8000'
    allowed = getattr(settings, 'ALLOWED_HOSTS', [])
    if allowed and allowed[0] not in ('*', ''):
        host = allowed[0]
    scheme = 'http' if host.startswith('localhost') or host.startswith('127.') else 'https'
    return f"{scheme}://{host}{path}"


def _render(template_name, ctx):
    try:
        return render_to_string(template_name, ctx)
    except Exception:
        return ''


def _org_admin(org):
    try:
        return org.users.filter(role='orgadmin').first()
    except Exception:
        return None


def retry_notification(log_id):
    """Retry a failed email/SMS from the admin."""
    try:
        log = NotificationLog.objects.get(pk=log_id)
    except NotificationLog.DoesNotExist:
        return None

    if log.channel == 'email':
        return send_email(
            to_email=log.to_email, subject=log.subject,
            body_text=log.body, event=log.event,
            user=log.recipient_user,
            related=log.related_object_repr,
            kind=log.kind,
            recipient_organization=log.recipient_organization,
            guest_booking=log.guest_booking,
        )
    if log.channel == 'sms':
        return send_sms(
            to_phone=log.to_phone, message=log.body, event=log.event,
            user=log.recipient_user, related=log.related_object_repr,
            kind=log.kind,
            recipient_organization=log.recipient_organization,
            guest_booking=log.guest_booking,
        )
    return log


# ============================================================
# EVENT: Guest booking created (pending)
# ============================================================
def on_booking_created(booking):
    listing = booking.listing
    org = booking.organization
    guest = booking.user

    pay_url = _frontend_url(f"/payments/start/{booking.pk}/")
    view_url = _frontend_url(f"/my/booking/{booking.pk}/")

    subject = f"Booking received — {listing.title} ({booking.reference})"
    text = (
        f"Hi {booking.customer_name},\n\n"
        f"We've received your booking request for {listing.title} "
        f"with {org.name}.\n\n"
        f"Booking reference: {booking.reference}\n"
        f"Total: KES {booking.total_amount}\n\n"
        f"Complete payment to confirm:\n{pay_url}\n\n"
        f"View booking: {view_url}\n\n— StayHub"
    )
    html = _render('notifications/emails/booking_created_guest.html', {
        'booking': booking, 'listing': listing, 'org': org,
        'pay_url': pay_url, 'view_url': view_url,
    })

    if booking.customer_email:
        send_email(
            to_email=booking.customer_email, subject=subject,
            body_text=text, body_html=html,
            event='booking_created_guest', kind='booking',
            user=guest, related=booking.reference,
            guest_booking=booking,
            recipient_organization=org,
        )

    if booking.customer_phone:
        send_sms(
            booking.customer_phone,
            f"StayHub: Booking {booking.reference} received for "
            f"{listing.title[:30]}. Total KES {booking.total_amount}. Pay: {pay_url}",
            event='booking_created_guest_sms', kind='booking',
            user=guest, related=booking.reference,
            guest_booking=booking,
            recipient_organization=org,
        )

    # In-app for the org owner
    send_inapp(
        event='booking_created_org', kind='booking',
        subject=f"New booking: {listing.title}",
        body=f"{booking.customer_name} booked {listing.title}. Ref {booking.reference}.",
        recipient_organization=org,
        guest_booking=booking,
        related=booking.reference,
        priority='high',
    )

    # Email to the org admin
    org_admin = _org_admin(org)
    if org_admin and org_admin.email:
        send_email(
            to_email=org_admin.email,
            subject=f"New booking — {listing.title}",
            body_text=(
                f"Hi {org_admin.display_name},\n\n"
                f"Guest: {booking.customer_name} "
                f"({booking.customer_email or 'no email'})\n"
                f"Phone: {booking.customer_phone or '—'}\n"
                f"Reference: {booking.reference}\n"
                f"Total: KES {booking.total_amount}\n"
                f"Status: Awaiting payment\n"
            ),
            event='booking_created_org_email', kind='booking',
            user=org_admin, related=booking.reference,
            recipient_organization=org,
            guest_booking=booking,
        )


# ============================================================
# EVENT: Payment succeeded
# ============================================================
def on_payment_succeeded(booking, attempt, receipt=None):
    listing = booking.listing
    org = booking.organization
    guest = booking.user

    view_url = _frontend_url(f"/my/booking/{booking.pk}/")
    receipt_url = _frontend_url(f"/payments/receipt/{receipt.pk}/") if receipt else ''

    if booking.customer_email:
        send_email(
            to_email=booking.customer_email,
            subject=f"Payment confirmed — {listing.title} ({booking.reference})",
            body_text=(
                f"Hi {booking.customer_name},\n\n"
                f"Your payment of KES {booking.amount_paid} has been received.\n"
                f"Reference: {booking.reference}\n"
                + (f"Receipt: {receipt_url}\n" if receipt_url else '')
                + f"\nView booking: {view_url}\n\n— StayHub"
            ),
            event='payment_succeeded_guest', kind='payment',
            user=guest, related=booking.reference,
            recipient_organization=org,
            guest_booking=booking,
        )

    if booking.customer_phone:
        send_sms(
            booking.customer_phone,
            f"StayHub: Payment of KES {booking.amount_paid} received. "
            f"Booking {booking.reference} confirmed.",
            event='payment_succeeded_guest_sms', kind='payment',
            user=guest, related=booking.reference,
            recipient_organization=org,
            guest_booking=booking,
        )

    send_inapp(
        event='payment_succeeded_org', kind='payment',
        subject=f"Payment received — {booking.reference}",
        body=f"{booking.customer_name} paid KES {booking.amount_paid} for {listing.title}.",
        recipient_organization=org,
        guest_booking=booking,
        related=booking.reference,
        priority='high',
    )

    org_admin = _org_admin(org)
    if org_admin and org_admin.email:
        send_email(
            to_email=org_admin.email,
            subject=f"Payment received — {listing.title}",
            body_text=(
                f"Hi {org_admin.display_name},\n\n"
                f"{booking.customer_name} paid KES {booking.amount_paid}.\n"
                f"Reference: {booking.reference}\n"
            ),
            event='payment_succeeded_org_email', kind='payment',
            user=org_admin, related=booking.reference,
            recipient_organization=org,
            guest_booking=booking,
        )


# ============================================================
# EVENT: Booking cancelled
# ============================================================
def on_booking_cancelled(booking):
    listing = booking.listing
    org = booking.organization
    guest = booking.user

    if booking.customer_email:
        send_email(
            to_email=booking.customer_email,
            subject=f"Booking cancelled — {listing.title} ({booking.reference})",
            body_text=(
                f"Hi {booking.customer_name},\n\n"
                f"Your booking {booking.reference} for {listing.title} "
                f"has been cancelled.\n\n— StayHub"
            ),
            event='booking_cancelled_guest', kind='booking',
            user=guest, related=booking.reference,
            recipient_organization=org,
            guest_booking=booking,
        )

    send_inapp(
        event='booking_cancelled_org', kind='booking',
        subject=f"Booking cancelled — {booking.reference}",
        body=f"{booking.customer_name} cancelled {listing.title}.",
        recipient_organization=org,
        guest_booking=booking,
        related=booking.reference,
    )


# ============================================================
# EVENT: Guest welcome
# ============================================================
def on_guest_welcome(user):
    if user.email:
        send_email(
            to_email=user.email,
            subject="Welcome to StayHub",
            body_text=(
                f"Hi {user.display_name or user.username},\n\n"
                f"Welcome to StayHub. Your account is ready.\n\n"
                f"Start exploring: {_frontend_url('/')}\n\n— StayHub"
            ),
            body_html=_render('notifications/emails/welcome_guest.html', {'user': user}),
            event='guest_welcome', kind='account',
            user=user,
        )


# ============================================================
# EVENT: Listing approved / rejected
# ============================================================
def on_listing_approved(listing, by_user=None):
    send_inapp(
        event='marketplace.listing.approved', kind='listing',
        subject=f"Listing approved — {listing.title}",
        body=f"Your listing '{listing.title}' is now live on the marketplace.",
        recipient_organization=listing.organization,
        related=str(listing),
    )
    admin = _org_admin(listing.organization)
    if admin and admin.email:
        send_email(
            to_email=admin.email,
            subject=f"Listing approved — {listing.title}",
            body_text=f"Your listing '{listing.title}' is now live on StayHub.",
            event='marketplace.listing.approved_email', kind='listing',
            user=admin, related=str(listing),
            recipient_organization=listing.organization,
        )


def on_listing_rejected(listing, note='', by_user=None):
    send_inapp(
        event='marketplace.listing.rejected', kind='listing',
        subject=f"Listing rejected — {listing.title}",
        body=note or 'Your listing was rejected.',
        recipient_organization=listing.organization,
        related=str(listing),
        priority='high',
    )


# ============================================================
# EVENT: Review created
# ============================================================
def on_review_created(review):
    send_inapp(
        event='marketplace.review.created', kind='review',
        subject=f"New review ({review.rating}★) for {review.listing.title}",
        body=review.body or '',
        recipient_organization=review.listing.organization,
        related=str(review),
    )


# ============================================================
# EVENT: Referral lifecycle
# ============================================================
def on_referral_created(referral):
    send_inapp(
        event='network.referral.created', kind='referral',
        subject=f"New referral {referral.reference}",
        body=f"{referral.guest_name} — {referral.service_needed}",
        recipient_organization=referral.to_org,
        related=referral.reference,
    )


def on_referral_status_changed(referral, new_status):
    send_inapp(
        event=f'network.referral.{new_status}', kind='referral',
        subject=f"Referral {referral.reference} {new_status}",
        body=f"{referral.guest_name} — {referral.service_needed}",
        recipient_organization=referral.from_org,
        related=referral.reference,
    )


# ============================================================
# EVENT: Order / booking status change (bnb, restaurant, laundry, tours)
# ============================================================
def on_order_status_changed(order, new_status, guest_booking=None):
    org = getattr(order, 'organization', None)
    if not org:
        return
    send_inapp(
        event=f'order.{new_status}', kind='order',
        subject=f"Order status → {new_status}",
        body=str(order),
        recipient_organization=org,
        guest_booking=guest_booking,
        related=str(order),
    )