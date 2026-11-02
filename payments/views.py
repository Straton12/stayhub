# payments/views.py
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from guestaccount.models import GuestBooking
from .models import PaymentAttempt, Receipt
from . import mpesa, services


# ============================================================
# HELPERS
# ============================================================
def _require_guest(request):
    return request.user.is_authenticated and getattr(request.user, 'is_guest', False)


def _require_org(request):
    return request.user.is_authenticated and getattr(request.user, 'is_org_member', False)


# ============================================================
# INITIATE
# ============================================================
@login_required
def initiate(request, booking_pk):
    if not _require_guest(request):
        return redirect('dashboard')

    booking = get_object_or_404(GuestBooking, pk=booking_pk, user=request.user)

    if booking.status == 'confirmed' and booking.amount_paid >= booking.total_amount:
        return redirect('payments:success', booking_pk=booking.pk)

    remaining = booking.balance

    if request.method == 'POST':
        method = request.POST.get('method', 'mpesa')
        phone = request.POST.get('phone', '').strip()

        if method == 'mpesa' and not phone:
            messages.error(request, 'Please enter an M-Pesa phone number.')
        else:
            try:
                attempt = services.create_attempt(
                    booking, method=method, phone=phone, user=request.user,
                )
            except ValueError as e:
                messages.error(request, str(e))
                return redirect('guestaccount:booking_detail', pk=booking.pk)

            if method == 'mpesa':
                return _start_mpesa(request, attempt, booking)
            elif method == 'card':
                return redirect('payments:card_stub', attempt_pk=attempt.pk)
            elif method == 'cash':
                # Cash is recorded by staff, not the guest. Bounce.
                messages.info(request, 'Cash payments are recorded by the business.')
                return redirect('guestaccount:booking_detail', pk=booking.pk)

    return render(request, 'payments/initiate.html', {
        'booking': booking,
        'remaining': remaining,
        'prefill_phone': booking.customer_phone or getattr(request.user, 'phone', ''),
        'sandbox': getattr(settings, 'PAYMENTS_SANDBOX', True),
        'policy': getattr(booking, 'payment_policy', 'pay_now'),
        'deposit_percent': getattr(booking.listing, 'deposit_percent', 0) or 0,
    })


# ============================================================
# M-PESA
# ============================================================
def _start_mpesa(request, attempt, booking):
    try:
        resp = mpesa.stk_push(
            phone=attempt.mpesa_phone or booking.customer_phone,
            amount=attempt.amount,
            reference=booking.reference,
            description=f"Payment for {booking.listing.title}"[:80],
        )
    except mpesa.MpesaError as e:
        services.fail_attempt(attempt, reason=str(e))
        messages.error(request, f'Could not start M-Pesa payment: {e}')
        return redirect('guestaccount:booking_detail', pk=booking.pk)

    attempt.mpesa_checkout_request_id = resp.get('CheckoutRequestID', '')
    attempt.mpesa_merchant_request_id = resp.get('MerchantRequestID', '')
    attempt.mpesa_result_code = resp.get('ResponseCode', '')
    attempt.mpesa_result_description = resp.get('ResponseDescription', '')
    attempt.provider_payload = resp.get('raw', {})
    attempt.status = 'processing'
    attempt.save()

    return redirect('payments:mpesa_wait', attempt_pk=attempt.pk)


@login_required
def mpesa_wait(request, attempt_pk):
    if not _require_guest(request):
        return redirect('dashboard')

    attempt = get_object_or_404(PaymentAttempt, pk=attempt_pk, user=request.user)
    booking = attempt.guest_booking
    sandbox = getattr(settings, 'PAYMENTS_SANDBOX', True)

    return render(request, 'payments/mpesa_wait.html', {
        'attempt': attempt,
        'booking': booking,
        'sandbox': sandbox,
    })


@login_required
def mpesa_sandbox_confirm(request, attempt_pk):
    if not _require_guest(request):
        return redirect('dashboard')
    if not getattr(settings, 'PAYMENTS_SANDBOX', True):
        messages.error(request, 'Sandbox confirmation is disabled.')
        return redirect('payments:mpesa_wait', attempt_pk=attempt_pk)

    attempt = get_object_or_404(PaymentAttempt, pk=attempt_pk, user=request.user)

    sim = mpesa.simulate_success(attempt.mpesa_checkout_request_id)
    services.complete_attempt(
        attempt,
        provider_receipt=sim.get('MpesaReceiptNumber', ''),
        extra={'sandbox_confirmation': sim},
    )
    return redirect('payments:success', booking_pk=attempt.guest_booking_id)


@csrf_exempt
def mpesa_callback(request):
    """Safaricom webhook. Idempotent — safe to be called twice."""
    import json
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}

    stk = (payload.get('Body') or {}).get('stkCallback') or {}
    checkout_id = stk.get('CheckoutRequestID', '')
    result_code = stk.get('ResultCode')
    result_desc = stk.get('ResultDesc', '')

    attempt = PaymentAttempt.objects.filter(
        mpesa_checkout_request_id=checkout_id,
    ).first()

    if not attempt:
        return JsonResponse({'ok': True, 'note': 'unknown attempt'})

    if attempt.status == 'succeeded':
        return JsonResponse({'ok': True, 'note': 'already completed'})

    if result_code == 0:
        items = (stk.get('CallbackMetadata') or {}).get('Item') or []
        receipt_no = ''
        for it in items:
            if it.get('Name') == 'MpesaReceiptNumber':
                receipt_no = it.get('Value') or ''
        services.complete_attempt(
            attempt, provider_receipt=receipt_no,
            extra={'callback_payload': payload},
        )
    else:
        services.fail_attempt(
            attempt, reason=result_desc,
            extra={'callback_payload': payload},
        )

    return JsonResponse({'ok': True})


# ============================================================
# CARD
# ============================================================
@login_required
def card_stub(request, attempt_pk):
    if not _require_guest(request):
        return redirect('dashboard')

    attempt = get_object_or_404(PaymentAttempt, pk=attempt_pk, user=request.user)
    return render(request, 'payments/card_stub.html', {
        'attempt': attempt,
        'booking': attempt.guest_booking,
    })


@login_required
def card_sandbox_confirm(request, attempt_pk):
    if not _require_guest(request):
        return redirect('dashboard')
    if not getattr(settings, 'PAYMENTS_SANDBOX', True):
        messages.error(request, 'Sandbox confirmation is disabled.')
        return redirect('payments:card_stub', attempt_pk=attempt_pk)

    attempt = get_object_or_404(PaymentAttempt, pk=attempt_pk, user=request.user)
    services.complete_attempt(
        attempt, provider_receipt='CARD-SANDBOX-' + attempt.reference,
    )
    return redirect('payments:success', booking_pk=attempt.guest_booking_id)


# ============================================================
# SUCCESS / FAILED
# ============================================================
@login_required
def success(request, booking_pk):
    if not _require_guest(request):
        return redirect('dashboard')

    booking = get_object_or_404(GuestBooking, pk=booking_pk, user=request.user)
    receipt = Receipt.objects.filter(guest_booking=booking).first()

    return render(request, 'payments/success.html', {
        'booking': booking,
        'receipt': receipt,
    })


@login_required
def failed(request, booking_pk):
    if not _require_guest(request):
        return redirect('dashboard')

    booking = get_object_or_404(GuestBooking, pk=booking_pk, user=request.user)
    attempts = booking.payment_attempts.order_by('-created_at')[:5]

    return render(request, 'payments/failed.html', {
        'booking': booking,
        'attempts': attempts,
    })


# ============================================================
# RECEIPTS
# ============================================================
@login_required
def receipt_detail(request, pk):
    receipt = get_object_or_404(
        Receipt.objects.select_related(
            'guest_booking', 'guest_booking__listing',
            'guest_booking__organization', 'payment_attempt',
        ),
        pk=pk,
    )

    user = request.user
    allowed = False
    if user.is_authenticated:
        if getattr(user, 'is_guest', False) and receipt.guest_booking.user_id == user.id:
            allowed = True
        elif getattr(user, 'is_superadmin', False):
            allowed = True
        elif user.organization_id and receipt.guest_booking.organization_id == user.organization_id:
            allowed = True

    if not allowed:
        messages.error(request, 'You do not have access to this receipt.')
        return redirect('marketplace:home')

    return render(request, 'payments/receipt_detail.html', {
        'receipt': receipt,
        'booking': receipt.guest_booking,
        'listing': receipt.guest_booking.listing,
        'organization': receipt.guest_booking.organization,
    })


@login_required
def receipt_pdf(request, pk):
    """
    Print-ready PDF. Uses ReportLab if installed; otherwise falls back
    to a printable HTML page (same template).
    """
    receipt = get_object_or_404(Receipt.objects.select_related(
        'guest_booking', 'guest_booking__listing',
        'guest_booking__organization', 'payment_attempt',
    ), pk=pk)

    user = request.user
    allowed = (
        getattr(user, 'is_superadmin', False)
        or (getattr(user, 'is_guest', False) and receipt.guest_booking.user_id == user.id)
        or (user.organization_id and receipt.guest_booking.organization_id == user.organization_id)
    )
    if not allowed:
        return HttpResponse('Access denied.', status=403)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{receipt.number}.pdf"'

        c = canvas.Canvas(response, pagesize=A4)
        width, height = A4
        y = height - 60

        c.setFont('Helvetica-Bold', 18)
        c.drawString(50, y, "StayHub Receipt")
        y -= 30
        c.setFont('Helvetica', 11)
        c.drawString(50, y, f"Receipt #: {receipt.number}")
        y -= 16
        c.drawString(50, y, f"Issued: {receipt.issued_at:%Y-%m-%d %H:%M}")
        y -= 16
        c.drawString(50, y, f"Business: {receipt.business_name}")
        y -= 16
        c.drawString(50, y, f"Customer: {receipt.customer_name}")
        y -= 16
        c.drawString(50, y, f"Description: {receipt.description}")
        y -= 24
        c.setFont('Helvetica-Bold', 12)
        c.drawString(50, y, f"Amount: {receipt.currency} {receipt.amount}")
        y -= 40
        c.setFont('Helvetica-Oblique', 10)
        c.drawString(50, y, "Thank you for using StayHub.")

        c.showPage()
        c.save()
        return response
    except Exception:
        # Fallback: printable HTML
        return receipt_detail(request, pk)


# ============================================================
# GUEST PAYMENT HISTORY
# ============================================================
@login_required
def history(request):
    if not _require_guest(request):
        return redirect('dashboard')

    attempts = (
        PaymentAttempt.objects
        .filter(guest_booking__user=request.user)
        .select_related('guest_booking', 'guest_booking__listing', 'guest_booking__organization')
        .order_by('-created_at')
    )
    receipts = (
        Receipt.objects
        .filter(guest_booking__user=request.user)
        .order_by('-issued_at')
    )
    return render(request, 'payments/history.html', {
        'attempts': attempts,
        'receipts': receipts,
    })


# ============================================================
# ORG PAYMENT LEDGER
# ============================================================
@login_required
def org_ledger(request):
    if not _require_org(request):
        return redirect('dashboard')

    org = request.user.organization
    attempts = (
        PaymentAttempt.objects
        .filter(guest_booking__organization=org)
        .select_related('guest_booking', 'guest_booking__listing', 'guest_booking__user')
        .order_by('-created_at')
    )
    receipts = (
        Receipt.objects
        .filter(guest_booking__organization=org)
        .order_by('-issued_at')
    )

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        attempts = attempts.filter(status=status_filter)

    return render(request, 'payments/org_ledger.html', {
        'attempts': attempts[:500],
        'receipts': receipts[:500],
        'status_filter': status_filter,
        'org': org,
    })


# ============================================================
# ORG: RECORD CASH PAYMENT
# ============================================================
@login_required
def record_cash(request, booking_pk):
    if not _require_org(request):
        return redirect('dashboard')

    booking = get_object_or_404(
        GuestBooking, pk=booking_pk,
        organization=request.user.organization,
    )

    if request.method == 'POST':
        amount_raw = request.POST.get('amount', '').strip()
        note = request.POST.get('note', '').strip()
        try:
            amount = Decimal(amount_raw)
            services.record_cash_payment(booking, amount,
                                         recorded_by=request.user, note=note)
            messages.success(request, f'Cash payment of {amount} recorded.')
        except Exception as e:
            messages.error(request, f'Could not record cash payment: {e}')

    return redirect('guestaccount:booking_detail', pk=booking.pk)