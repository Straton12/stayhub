# payments/mpesa.py
"""
M-Pesa Daraja client.

Sandbox (PAYMENTS_SANDBOX=True): does NOT call Safaricom.
Live:            calls Daraja STK Push with settings.MPESA_*.
"""

import base64
import json
import uuid
from datetime import datetime

import requests
from django.conf import settings


class MpesaError(Exception):
    pass


def _daraja_base():
    if getattr(settings, 'MPESA_ENV', 'sandbox') == 'production':
        return 'https://api.safaricom.co.ke'
    return 'https://sandbox.safaricom.co.ke'


def _password_and_timestamp():
    shortcode = settings.MPESA_SHORTCODE
    passkey = settings.MPESA_PASSKEY
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    raw = f"{shortcode}{passkey}{ts}".encode()
    password = base64.b64encode(raw).decode()
    return password, ts


def _access_token():
    key = settings.MPESA_CONSUMER_KEY
    secret = settings.MPESA_CONSUMER_SECRET
    if not key or not secret:
        raise MpesaError('M-Pesa consumer key/secret not configured.')

    url = f"{_daraja_base()}/oauth/v1/generate?grant_type=client_credentials"
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    r = requests.get(url, headers={'Authorization': f'Basic {auth}'}, timeout=20)
    if r.status_code != 200:
        raise MpesaError(f"Auth failed: {r.status_code} {r.text}")
    return r.json().get('access_token')


def stk_push(phone, amount, reference, description='StayHub booking'):
    phone = _normalise_phone(phone)
    amount = int(float(amount))

    if getattr(settings, 'PAYMENTS_SANDBOX', True):
        fake_id = 'SANDBOX-' + uuid.uuid4().hex[:12].upper()
        return {
            'CheckoutRequestID': fake_id,
            'MerchantRequestID': 'SANDBOX-MR-' + uuid.uuid4().hex[:8].upper(),
            'ResponseCode': '0',
            'ResponseDescription': 'Sandbox success',
            'CustomerMessage': 'Sandbox: Enter M-Pesa PIN on your phone to complete payment.',
            'raw': {'mode': 'sandbox', 'phone': phone, 'amount': amount, 'reference': reference},
        }

    token = _access_token()
    password, ts = _password_and_timestamp()
    payload = {
        'BusinessShortCode': settings.MPESA_SHORTCODE,
        'Password': password,
        'Timestamp': ts,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': amount,
        'PartyA': phone,
        'PartyB': settings.MPESA_SHORTCODE,
        'PhoneNumber': phone,
        'CallBackURL': settings.MPESA_CALLBACK_URL,
        'AccountReference': reference[:12],
        'TransactionDesc': description[:80],
    }

    url = f"{_daraja_base()}/mpesa/stkpush/v1/processrequest"
    r = requests.post(
        url,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        data=json.dumps(payload),
        timeout=25,
    )
    try:
        data = r.json()
    except Exception:
        raise MpesaError(f"Bad response from Daraja: {r.status_code} {r.text}")

    if r.status_code != 200:
        raise MpesaError(f"STK push failed: {r.status_code} {data}")

    data['raw'] = data.copy()
    return data


def _normalise_phone(phone):
    digits = ''.join(c for c in (phone or '') if c.isdigit())
    if digits.startswith('0'):
        digits = '254' + digits[1:]
    elif digits.startswith('7') and len(digits) == 9:
        digits = '254' + digits
    elif digits.startswith('254'):
        pass
    else:
        digits = '254' + digits.lstrip('0')
    return digits


def simulate_success(checkout_request_id):
    return {
        'ResultCode': 0,
        'ResultDesc': 'The service request is processed successfully.',
        'CheckoutRequestID': checkout_request_id,
        'MpesaReceiptNumber': 'SB' + uuid.uuid4().hex[:8].upper(),
    }