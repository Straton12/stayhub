<div align="center">

# 🏢 StayHub
### *Enterprise-Grade Hospitality, Booking & Multi-Service Marketplace Ecosystem*

[![Django](https://img.shields.io/badge/Django-5.0+-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-SQLite%20%2F%20PostgreSQL-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![M-Pesa](https://img.shields.io/badge/Gateway-M--Pesa%20Daraja-green?style=for-the-badge)](https://developer.safaricom.co.ke/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

**A unified Django platform for hospitality, tours, dining, laundry, and marketplace commerce — with M-Pesa payments, guest self-registration, and multi-channel notifications built in.**

</div>

---

## 📖 Table of Contents

1. [Overview](#-overview)
2. [Key Highlights](#-key-highlights)
3. [Architecture & Modular Directory Structure](#-architecture--modular-directory-structure)
4. [Detailed Application Breakdown](#-detailed-application-breakdown)
5. [Tech Stack & Dependencies](#-tech-stack--dependencies)
6. [Prerequisites](#-prerequisites)
7. [End-to-End Installation & Setup Guide](#-end-to-end-installation--setup-guide)
8. [Environment Variables Reference](#-environment-variables-reference)
9. [Database Management & Migrations](#-database-management--migrations)
10. [Payment Gateway Integration (M-Pesa Daraja)](#-payment-gateway-integration-m-pesa-daraja)
11. [Notification Engine (Email & SMS)](#-notification-engine-email--sms)
12. [Running Tests & Development Workflow](#-running-tests--development-workflow)
13. [Production Deployment Guide](#-production-deployment-guide)
14. [Troubleshooting](#-troubleshooting)
15. [Contributing Guidelines](#-contributing-guidelines)
16. [License](#-license)
17. [Author & Maintainers](#-author--maintainers)

---

## 📖 Overview

**StayHub** is an all-in-one, highly scalable web platform built with **Django**. It is designed to bridge the gap between hospitality management, multi-vendor services, and consumer marketplaces.

By unifying short-stay accommodations (BnB), tour bookings, restaurant dining, garment care services, e-commerce storefronts, and Safaricom M-Pesa mobile money processing into a single integrated platform, StayHub delivers a complete operational solution for modern service enterprises.

### The Problem StayHub Solves

Hospitality and travel businesses typically operate **five or more separate platforms**: a booking engine for rooms, a separate tours widget, a third-party restaurant ordering portal, a laundry app, and an online shop. This fragmentation causes:

- ❌ Duplicated user accounts across platforms
- ❌ Inconsistent branding and UX
- ❌ Scattered analytics and reporting
- ❌ Multiple billing relationships
- ❌ Disjointed customer experience

### The StayHub Solution

- ✅ **One Django project** — ten modular apps under one codebase
- ✅ **One custom `User` model** (`accounts.User`) shared by staff and guests
- ✅ **One admin back-office** — manage listings, orders, and bookings in one place
- ✅ **One payment integration** — M-Pesa Daraja (STK Push) with sandbox mode
- ✅ **One notification pipeline** — email + SMS, pluggable backends
- ✅ **One deployment** — same server, same database, same secrets

---

## ✨ Key Highlights

| Highlight | Description |
|-----------|-------------|
| **Modular monolith** | Ten apps, each owning its own models, views, templates, and admin. |
| **Custom user model** | `AUTH_USER_MODEL = 'accounts.User'` — supports staff/org and guests. |
| **Guest self-registration** | Public users sign up via `ALLOW_GUEST_SIGNUP`, land on `/my/`. |
| **Guest profile middleware** | `GuestProfileMiddleware` auto-attaches a `GuestProfile` on every request (no-op for staff). |
| **Public marketplace** | Full storefront with categories, cart, and wishlist. |
| **Context processor** | `marketplace_context` exposes cart/wishlist counts to every template globally. |
| **M-Pesa Daraja** | STK Push integration, sandbox out of the box. |
| **Notification engine** | Console, email (SMTP), and SMS (Africa's Talking) backends. |
| **Humanised admin** | `django.contrib.humanize`, `sitemaps`, `syndication`, `redirects`. |
| **Timezone-aware** | `Africa/Nairobi`, `USE_TZ = True` — correct for East African operators. |

---

## 🏗️ Architecture & Modular Directory Structure

StayHub uses a **modular monolith** design pattern, isolating each business domain into a standalone Django application within the project root:

```text
stayhub/
├── accounts/                  # User authentication & permissions (custom User model)
├── bnb/                       # Short-stay rental listings and room reservations
├── guestaccount/              # Guest profiles & automated session middleware
├── laundry/                   # Garment service ordering and status tracking
├── marketplace/               # Public e-commerce storefront, carts & wishlists
├── network/                   # Provider network directory & business listings
├── notifications/             # Multi-channel notification pipeline (console/email/SMS)
├── payments/                  # M-Pesa Daraja STK push payment integration engine
├── restaurant/                # Dining menus, online ordering & table bookings
├── stayhub_project/           # Core Django settings, WSGI/ASGI, and routing configs
├── tours/                     # Tour itineraries, excursion scheduling & bookings
├── static/                    # Global frontend static assets (CSS, JS, images)
├── staticfiles/               # collectstatic output (git-ignored)
├── media/                     # User-uploaded files, profile pictures, and assets
├── db.sqlite3                 # Local SQLite database instance (git-ignored)
├── manage.py                  # Django administrative script CLI
├── requirements.txt           # Python package dependency manifest
├── .env                       # Local private environment variables (git-ignored)
├── .env.example               # Template environment configuration file
├── .gitignore                 # Git ignore rules
└── README.md                  # This file
```

### Request Lifecycle

```text
Browser
   │
   ▼
stayhub_project/urls.py  ──►  routes by prefix
   │
   ├── /admin/          ──►  Django admin
   ├── /accounts/       ──►  accounts.urls
   ├── /bnb/            ──►  bnb.urls
   ├── /tours/          ──►  tours.urls
   ├── /restaurant/     ──►  restaurant.urls
   ├── /laundry/        ──►  laundry.urls
   ├── /network/        ──►  network.urls
   ├── /marketplace/    ──►  marketplace.urls
   ├── /my/             ──►  guestaccount.urls
   ├── /payments/       ──►  payments.urls
   └── /                ──►  marketplace homepage
   │
   ▼
Middleware chain (security → sessions → auth → messages → guestprofile)
   │
   ▼
View → Model (DB) → Template → Response
```

---

## 🧩 Detailed Application Breakdown

### 👥 `accounts` — Identity & Access
- Custom `User` model set via `AUTH_USER_MODEL = 'accounts.User'`.
- Staff/org users land on `/dashboard/` after login (`LOGIN_REDIRECT_URL`).
- Guests are redirected to `/my/` (`GUEST_HOME_URL`).
- `LOGIN_URL = '/accounts/login/'`, `LOGOUT_REDIRECT_URL = '/'`.
- Password validators enforced (similarity, length, common, numeric).

### 🏡 `bnb` — Bed & Breakfast / Short-Stay
- Property listings with photos, amenities, and per-night pricing.
- Date-based availability windows.
- Reservation flow with guest count.
- Hosts manage listings via Django admin.

### 🗺 `tours` — Tour Packages
- Multi-day and day-trip tour definitions.
- Reservation system with preferred dates and pax counts.
- Public listing and detail pages.

### 🍽 `restaurant` — Dining & Orders
- Menu categories and items with prices.
- Order placement and table reservations.
- Kitchen status pipeline (received → preparing → ready → served).

### 🧺 `laundry` — Garment Care
- Pickup requests (weight or item count).
- Status lifecycle: `received → washing → drying → ready → delivered`.
- Optional rider/scheduling fields.

### 🛰 `network` — Provider Network
- Partner provider registry across services.
- Public-facing directory of the network.

### 🛒 `marketplace` — Public Storefront
- **Categories** — hierarchical product/service taxonomy.
- **Cart** — persistent per user/session.
- **Wishlist** — saved items for later.
- **Context processor** (`marketplace.context_processors.marketplace_context`) — exposes categories + cart/wishlist counts to every template.
- **Homepage** — mounted at `/` (`MARKETPLACE_HOME_URL`).

### 👤 `guestaccount` — Guest Self-Registration
- Registration allowed only when `ALLOW_GUEST_SIGNUP = True`.
- **`GuestProfileMiddleware`** — attaches a `GuestProfile` to every request; safe no-op for staff users.
- Guest dashboard mounted at `/my/`.

### 💳 `payments` — M-Pesa Daraja
- STK Push (Lipa na M-Pesa) integration.
- Sandbox mode enabled via `PAYMENTS_SANDBOX = True`.
- Callback handler for payment confirmations.
- Currency: `KES` (`PAYMENTS_CURRENCY`).

### 🔔 `notifications` — Email + SMS
- **Email** — Django console backend in dev; SMTP in prod.
- **SMS** — `ConsoleSMSBackend` in dev; `africastalking` in prod.
- Triggered by order, booking, and payment events.

### 🛠 `stayhub_project` — Project Configuration
- `settings.py` — settings and environment loading.
- `urls.py` — top-level routing.
- `wsgi.py` / `asgi.py` — server entry points.

### Global Django Contributions Enabled
- `django.contrib.admin` — admin panel
- `django.contrib.humanize` — `intcomma`, `naturaltime`
- `django.contrib.sitemaps` — `sitemap.xml`
- `django.contrib.syndication` — RSS / Atom feeds
- `django.contrib.redirects` — admin-managed redirects
- `django.contrib.sites` — multi-site framework

---

## 🧱 Tech Stack & Dependencies

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.10+ |
| Framework | Django | 5.0+ |
| Database (dev) | SQLite | 3.x |
| Database (prod) | PostgreSQL | 14+ |
| Payments | M-Pesa Daraja API | v2 |
| SMS | Africa's Talking | — |
| Email | Django SMTP / console | — |
| Static files | WhiteNoise / Nginx | — |
| WSGI server | Gunicorn | — |
| Env loading | `python-dotenv` | — |
| HTTP client | `requests` | — |

---

## ✅ Prerequisites

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- **pip** — bundled with Python
- **Git** — [git-scm.com](https://git-scm.com/)
- (Optional) **PostgreSQL 14+** — for production
- (Optional) **ngrok** — for testing M-Pesa callbacks

Verify:

```bash
python --version
pip --version
git --version
```

---

## 🚀 End-to-End Installation & Setup Guide

### 1. Clone the repository

```bash
git clone https://github.com/Straton12/stayhub.git
cd stayhub
```

### 2. Create and activate a virtual environment

**Windows (Git Bash / MINGW64):**
```bash
python -m venv venv
source venv/Scripts/activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` in your prompt.

### 3. Upgrade pip and install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

If `requirements.txt` is missing, install directly:

```bash
pip install django python-dotenv requests
pip freeze > requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the values (see [Environment Variables Reference](#-environment-variables-reference)).

### 5. Apply migrations

```bash
python manage.py migrate
```

### 6. Create a superuser

```bash
python manage.py createsuperuser
```

### 7. (Optional) Load sample data

```bash
# If a fixture exists
python manage.py loaddata fixtures/sample.json
```

### 8. Collect static files (optional in dev)

```bash
python manage.py collectstatic --noinput
```

### 9. Run the development server

```bash
python manage.py runserver
```

Open:

- 🛍  Marketplace homepage → <http://127.0.0.1:8000/>
- 👤 Guest dashboard → <http://127.0.0.1:8000/my/>
- 🛠 Admin panel → <http://127.0.0.1:8000/admin/>

To expose to your LAN:

```bash
python manage.py runserver 0.0.0.0:8000
```

---

## ⚙️ Environment Variables Reference

| Variable | Default | Required | Purpose |
|----------|---------|----------|---------|
| `SECRET_KEY` | *(dev fallback)* | ✅ prod | Django cryptographic key |
| `DEBUG` | `True` | ✅ prod | Set `False` in prod |
| `ALLOWED_HOSTS` | `*` | ✅ prod | Comma-separated hosts |
| `MPESA_ENV` | `sandbox` | prod | `sandbox` or `production` |
| `MPESA_CONSUMER_KEY` | — | live | Daraja consumer key |
| `MPESA_CONSUMER_SECRET` | — | live | Daraja consumer secret |
| `MPESA_SHORTCODE` | `174379` | live | Paybill / Till number |
| `MPESA_PASSKEY` | — | live | Daraja passkey |
| `MPESA_CALLBACK_URL` | — | live | Public HTTPS callback URL |
| `PAYMENTS_CURRENCY` | `KES` | — | ISO currency code |
| `AFRICASTALKING_USERNAME` | — | SMS prod | AT username |
| `AFRICASTALKING_API_KEY` | — | SMS prod | AT API key |
| `EMAIL_HOST` | — | email prod | SMTP host |
| `EMAIL_PORT` | `587` | email prod | SMTP port |
| `EMAIL_HOST_USER` | — | email prod | SMTP user |
| `EMAIL_HOST_PASSWORD` | — | email prod | SMTP password |

### Example `.env`

```dotenv
SECRET_KEY=change-me-to-a-random-64-char-string
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

MPESA_ENV=sandbox
MPESA_CONSUMER_KEY=
MPESA_CONSUMER_SECRET=
MPESA_SHORTCODE=174379
MPESA_PASSKEY=
MPESA_CALLBACK_URL=

AFRICASTALKING_USERNAME=
AFRICASTALKING_API_KEY=
```

Generate a strong secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

---

## 🗄 Database Management & Migrations

### Apply migrations
```bash
python manage.py migrate
```

### Make migrations after model changes
```bash
python manage.py makemigrations
python manage.py migrate
```

### Migrate a specific app
```bash
python manage.py makemigrations marketplace
python manage.py migrate marketplace
```

### Inspect migration status
```bash
python manage.py showmigrations
```

### Roll back a migration
```bash
python manage.py migrate marketplace 0002
```

### Reset the dev database (⚠️ destructive)
```bash
rm db.sqlite3
python manage.py migrate
python manage.py createsuperuser
```

### Switch to PostgreSQL

1. Install driver:
   ```bash
   pip install psycopg2-binary
   ```
2. Update `settings.py`:
   ```python
   DATABASES = {
       'default': {
           'ENGINE': 'django.db.backends.postgresql',
           'NAME': os.environ['DB_NAME'],
           'USER': os.environ['DB_USER'],
           'PASSWORD': os.environ['DB_PASSWORD'],
           'HOST': os.environ.get('DB_HOST', 'localhost'),
           'PORT': os.environ.get('DB_PORT', '5432'),
       }
   }
   ```
3. Re-run migrations.

---

## 💳 Payment Gateway Integration (M-Pesa Daraja)

StayHub ships with **M-Pesa Daraja** integration. By default it runs in **sandbox mode** — no real money moves.

### Sandbox defaults (`settings.py`)

```python
PAYMENTS_SANDBOX = True
MPESA_ENV = 'sandbox'
MPESA_SHORTCODE = '174379'
PAYMENTS_CURRENCY = 'KES'
```

### The STK Push flow

```text
Guest clicks "Pay with M-Pesa"
        │
        ▼
POST /payments/mpesa/stkpush/     (server → Daraja)
        │
        ▼
Daraja sends STK prompt to user's phone
        │
        ▼
User enters M-Pesa PIN
        │
        ▼
Daraja → POST /payments/mpesa/callback/   (async, HTTPS required)
        │
        ▼
Server marks order paid → triggers notification
```

### Going live — checklist

1. Register at <https://developer.safaricom.co.ke/>
2. Create an app → get **Consumer Key** and **Consumer Secret**
3. Get the **Passkey** for your shortcode
4. Set a public HTTPS callback URL (use **ngrok** for testing):
   ```bash
   ngrok http 8000
   # → https://abc123.ngrok.io
   ```
5. Update `.env`:
   ```dotenv
   MPESA_ENV=production
   MPESA_CONSUMER_KEY=xxx
   MPESA_CONSUMER_SECRET=xxx
   MPESA_SHORTCODE=xxxxxx
   MPESA_PASSKEY=xxx
   MPESA_CALLBACK_URL=https://yourdomain.com/payments/mpesa/callback/
   ```
6. In `settings.py`, flip `PAYMENTS_SANDBOX = False`.

### Testing sandbox payments

Use test MSISDN `254708374149` (Safaricom sandbox). Payments will *appear* to succeed — no real money is transferred.

---

## 🔔 Notification Engine (Email & SMS)

StayHub's `notifications` app exposes two pluggable backends.

### Development (defaults)

```python
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
SMS_BACKEND = 'notifications.backends.ConsoleSMSBackend'
```

Both **print to the terminal** — nothing is sent externally. Perfect for dev.

### Production — Email (SMTP)

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ['EMAIL_HOST']
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = os.environ['EMAIL_HOST_PASSWORD']
DEFAULT_FROM_EMAIL = 'StayHub <noreply@yourdomain.com>'
```

### Production — SMS (Africa's Talking)

```python
SMS_BACKEND = 'notifications.backends.AfricaStalkingSMSBackend'
AFRICASTALKING_USERNAME = os.environ['AFRICASTALKING_USERNAME']
AFRICASTALKING_API_KEY = os.environ['AFRICASTALKING_API_KEY']
```

### Trigger points

| Event | Email | SMS |
|-------|-------|-----|
| Guest registration | ✅ | ✅ |
| Order placed | ✅ | ✅ |
| Order shipped | ✅ | ✅ |
| Booking confirmed | ✅ | ✅ |
| Payment received | ✅ | ✅ |
| Payment failed | ✅ | — |

---

## 🧪 Running Tests & Development Workflow

### Run the whole test suite
```bash
python manage.py test
```

### Run a single app
```bash
python manage.py test marketplace
python manage.py test payments
```

### Run a specific test class
```bash
python manage.py test payments.tests.MpesaCallbackTests
```

### Coverage (optional)
```bash
pip install coverage
coverage run manage.py test
coverage report -m
coverage html      # open htmlcov/index.html
```

### Recommended dev workflow

```bash
# 1. Pull latest
git pull origin main

# 2. Activate venv
source venv/Scripts/activate

# 3. Install any new deps
pip install -r requirements.txt

# 4. Apply migrations
python manage.py migrate

# 5. Run tests
python manage.py test

# 6. Run server
python manage.py runserver
```

### Conventional Commits

| Prefix | Purpose |
|--------|---------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation |
| `style:` | Formatting, no logic change |
| `refactor:` | Code restructure |
| `test:` | Tests |
| `chore:` | Tooling, deps |

Example: `git commit -m "feat(marketplace): add wishlist toggle"`

---

## 🚢 Production Deployment Guide

### Pre-deployment checklist

- [ ] `DEBUG = False`
- [ ] `SECRET_KEY` loaded from env (never hardcoded)
- [ ] `ALLOWED_HOSTS` set to your real domain(s)
- [ ] Switch to PostgreSQL
- [ ] `python manage.py collectstatic`
- [ ] Serve static files via WhiteNoise or Nginx
- [ ] Serve media from Nginx or S3
- [ ] HTTPS (Let's Encrypt)
- [ ] Real `MPESA_CALLBACK_URL` (HTTPS)
- [ ] Real email + SMS backends
- [ ] Gunicorn + systemd/supervisor
- [ ] Database backups scheduled
- [ ] `PAYMENTS_SANDBOX = False` **only** when going live
- [ ] Log rotation configured
- [ ] Monitoring & error reporting (Sentry, etc.)

### Gunicorn example

```bash
pip install gunicorn
gunicorn stayhub_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
```

### Nginx reverse proxy (excerpt)

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location /static/ { alias /srv/stayhub/staticfiles/; }
    location /media/  { alias /srv/stayhub/media/; }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### systemd service

```ini
[Unit]
Description=StayHub Gunicorn
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/srv/stayhub
EnvironmentFile=/srv/stayhub/.env
ExecStart=/srv/stayhub/venv/bin/gunicorn stayhub_project.wsgi:application --bind 127.0.0.1:8000 --workers 3
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now stayhub
```

---

## 🧯 Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'django'` | Activate venv, then `pip install -r requirements.txt` |
| `no such table: ...` | Run `python manage.py migrate` |
| `Error: That port is already in use.` | `python manage.py runserver 8001` |
| `CSRF verification failed` | Ensure CSRF middleware is enabled |
| `Static files 404` | Run `collectstatic`; check `STATIC_URL` / `STATICFILES_DIRS` |
| `Permission denied (publickey)` on push | Add SSH key to GitHub or use HTTPS + PAT |
| `M-Pesa STK push fails` | Check callback URL is HTTPS & reachable; verify passkey/shortcode |
| `UnicodeEncodeError` in Windows console | `set PYTHONUTF8=1` before running |
| Migrations out of sync | `python manage.py makemigrations` then `migrate` |
| Stale `.pyc` files | `find . -name "*.pyc" -delete`; or `python manage.py clean_pyc` |

---

## 🤝 Contributing Guidelines

1. **Fork** the repository.
2. **Clone** your fork:
   ```bash
   git clone https://github.com/<your-user>/stayhub.git
   ```
3. **Create a branch**:
   ```bash
   git checkout -b feature/my-feature
   ```
4. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/):
   ```bash
   git commit -m "feat(marketplace): add wishlist toggle"
   ```
5. **Push**:
   ```bash
   git push origin feature/my-feature
   ```
6. **Open a Pull Request** with a clear description, screenshots if UI, and test evidence.

### Branch naming

| Prefix | Use |
|--------|-----|
| `feature/` | New feature |
| `fix/` | Bug fix |
| `docs/` | Documentation |
| `refactor/` | Restructure |
| `chore/` | Tooling |

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

```
MIT License

Copyright (c) 2025 Straton12

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 👤 Author & Maintainers

**Straton12** — [@Straton12](https://github.com/Straton12)

Contributions, issues, and feature requests are welcome.
Open an issue at <https://github.com/Straton12/stayhub/issues>.

---

<div align="center">

**⭐ If StayHub helped you build something, consider starring the repo!**

*Built with ❤️ using Django.*

</div>