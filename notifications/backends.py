# notifications/backends.py
"""
SMS backends.

Configure via settings:
    SMS_BACKEND = 'notifications.backends.ConsoleSMSBackend'
  or
    SMS_BACKEND = 'notifications.backends.AfricaTalkingSMSBackend'
"""

import requests
from django.conf import settings


class BaseSMSBackend:
    def send(self, phone, message):
        """
        Return (success: bool, provider_id: str, error: str).
        Never raise — return failures so the caller can log them.
        """
        raise NotImplementedError


class ConsoleSMSBackend(BaseSMSBackend):
    """Dev backend: prints the SMS to the console."""

    def send(self, phone, message):
        print('=' * 60)
        print(f"[SMS] to: {phone}")
        print(f"[SMS] message: {message}")
        print('=' * 60)
        return (True, 'console', '')


class AfricaTalkingSMSBackend(BaseSMSBackend):
    """
    Production backend for Africa's Talking SMS.
    Requires AFRICASTALKING_USERNAME and AFRICASTALKING_API_KEY.
    """

    def send(self, phone, message):
        username = getattr(settings, 'AFRICASTALKING_USERNAME', '')
        api_key  = getattr(settings, 'AFRICASTALKING_API_KEY', '')
        if not username or not api_key:
            return (False, '', "Africa's Talking credentials not configured.")

        recipient = (phone or '').strip()
        if recipient.startswith('0'):
            recipient = '+254' + recipient[1:]
        elif recipient.startswith('254'):
            recipient = '+' + recipient

        url = 'https://api.africastalking.com/version1/messaging'
        headers = {
            'apiKey': api_key,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
        }
        data = {'username': username, 'to': recipient, 'message': message}
        try:
            r = requests.post(url, headers=headers, data=data, timeout=20)
            if r.status_code in (200, 201):
                payload = r.json() if r.text else {}
                recipients = (payload.get('SMSMessageData') or {}).get('Recipients') or []
                if recipients:
                    return (True, recipients[0].get('messageId', ''), '')
                return (True, '', '')
            return (False, '', f"{r.status_code} {r.text[:200]}")
        except requests.RequestException as e:
            return (False, '', str(e))


def get_sms_backend():
    from importlib import import_module
    path = getattr(settings, 'SMS_BACKEND',
                   'notifications.backends.ConsoleSMSBackend')
    module_path, class_name = path.rsplit('.', 1)
    module = import_module(module_path)
    return getattr(module, class_name)()