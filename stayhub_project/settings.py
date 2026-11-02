# stayhub_project/settings.py

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-9##k@&i3i4v_!cmdt%)@m%^iyhz-33^^_o%b%6c0e&bf_xhc5q'

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',     # intcomma, naturaltime
    'django.contrib.sitemaps',     # sitemap.xml
    'django.contrib.syndication',  # RSS / Atom feeds
    'django.contrib.redirects',    # admin-managed redirects (needs migrate)
    'django.contrib.sites',       # ← add this

    # Existing apps
    'accounts',
    'bnb',
    'tours',
    'restaurant',
    'laundry',
    'network',

    # New apps
    'marketplace',
    'guestaccount',
    'payments',
    'notifications',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # New: attach a GuestProfile to every logged-in guest (safe no-op for staff)
    'guestaccount.middleware.GuestProfileMiddleware',
]

ROOT_URLCONF = 'stayhub_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                # New: exposes marketplace categories + cart/wishlist counts globally
                'marketplace.context_processors.marketplace_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'stayhub_project.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'          # staff/org landing (unchanged)
LOGOUT_REDIRECT_URL = '/'          # → marketplace homepage

# Where a guest goes after login (used by marketplace redirects)
GUEST_HOME_URL = '/my/'

# Where the public marketplace lives
MARKETPLACE_HOME_URL = '/'

# ---------------------------------------------------------------------------
# Guest self-registration
# ---------------------------------------------------------------------------
ALLOW_GUEST_SIGNUP = True

# ---------------------------------------------------------------------------
# Payments (sandbox by default — flip to False for real M-Pesa)
# ---------------------------------------------------------------------------
PAYMENTS_SANDBOX = True
MPESA_ENV = 'sandbox'                       # 'sandbox' | 'production'
MPESA_CONSUMER_KEY = ''                     # fill in when going live
MPESA_CONSUMER_SECRET = ''
MPESA_SHORTCODE = '174379'                  # Daraja sandbox default
MPESA_PASSKEY = ''                          # fill in when going live
MPESA_CALLBACK_URL = ''                     # e.g. https://yourdomain.com/payments/mpesa/callback/
PAYMENTS_CURRENCY = 'KES'

# ---------------------------------------------------------------------------
# Notifications (dev: prints to console; prod: set EMAIL_BACKEND + SMS keys)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'StayHub <noreply@stayhub.local>'

SMS_BACKEND = 'notifications.backends.ConsoleSMSBackend'   # 'africastalking' for prod
AFRICASTALKING_USERNAME = ''
AFRICASTALKING_API_KEY = ''