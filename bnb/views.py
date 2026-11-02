# bnb/views.py

from datetime import timedelta
from decimal import Decimal
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db import models
from django.db.models import Case, When, IntegerField
from .forms import (
    PropertyForm, GuestForm, BookingForm,
    HousekeepingTaskForm, MaintenanceRequestForm,
    ExpenseForm, ExpenseCategoryForm, RevenueForm,
    InvoiceForm, PaymentForm, StaffMemberForm, ReviewForm,
)
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from .models import (
    Property, Guest, Booking,
    PricingRule,
    HousekeepingTask, MaintenanceRequest,
    Expense, ExpenseCategory, Revenue,
    Invoice, Payment, StaffMember, Review, ActivityLog,
    Amenity, REVENUE_STATUSES, OUTSTANDING_STATUSES, INVOICE_OPEN_STATUSES,
)
from collections import defaultdict
from .services import (
    notify as _notify,
    publish_property as _publish_property,
    sync_guest_booking_from_booking as _sync_guest_booking_from_booking,
    lock_listing_for_booking as _lock_listing_for_booking,
    release_listing_for_booking as _release_listing_for_booking,
)


from django.db.models.functions import TruncMonth




REVENUE_STATUSES = ('confirmed', 'checked_in', 'checked_out')



# bnb/views.py — append

from datetime import date, datetime, timedelta
from calendar import monthrange



from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncQuarter, TruncYear

from django.utils import timezone

from .models import LedgerEntry, get_financial_settings


# ============================================================
#  RANGE PARSING
# ============================================================
RANGE_PRESETS = {
    'today':      'Today',
    'week':       'This week',
    'month':      'This month',
    'quarter':    'This quarter',
    'year':       'This year',
    'last_week':  'Last week',
    'last_month': 'Last month',
    'last_quarter': 'Last quarter',
    'last_year':  'Last year',
    'ytd':        'Year to date',
    'all':        'All time',
    'custom':     'Custom range',
}


def _resolve_range(request):
    """
    Parse ?range=..., ?start=YYYY-MM-DD, ?end=YYYY-MM-DD
    Returns (start_dt, end_dt, label, range_key).
    """
    range_key = request.GET.get('range', 'month')

    today = timezone.now().date()

    def dt(d, end=False):
        t = datetime.max.time() if end else datetime.min.time()
        return timezone.make_aware(datetime.combine(d, t))

    if range_key == 'today':
        return dt(today), dt(today, end=True), 'Today', range_key

    if range_key == 'week':
        # Monday → Sunday
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return dt(start), dt(end, end=True), 'This week', range_key

    if range_key == 'last_week':
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return dt(start), dt(end, end=True), 'Last week', range_key

    if range_key == 'month':
        start = today.replace(day=1)
        end = today.replace(day=monthrange(today.year, today.month)[1])
        return dt(start), dt(end, end=True), 'This month', range_key

    if range_key == 'last_month':
        first = today.replace(day=1)
        end = first - timedelta(days=1)
        start = end.replace(day=1)
        return dt(start), dt(end, end=True), 'Last month', range_key

    if range_key == 'quarter':
        q = (today.month - 1) // 3 + 1
        start_month = 3 * (q - 1) + 1
        start = today.replace(month=start_month, day=1)
        end_month = start_month + 2
        end = today.replace(
            month=end_month,
            day=monthrange(today.year, end_month)[1],
        )
        return dt(start), dt(end, end=True), 'This quarter', range_key

    if range_key == 'last_quarter':
        q = (today.month - 1) // 3 + 1
        prev_q = q - 1 if q > 1 else 4
        year = today.year if q > 1 else today.year - 1
        start_month = 3 * (prev_q - 1) + 1
        start = date(year, start_month, 1)
        end_month = start_month + 2
        end = date(year, end_month, monthrange(year, end_month)[1])
        return dt(start), dt(end, end=True), 'Last quarter', range_key

    if range_key == 'year':
        start = today.replace(month=1, day=1)
        end = today.replace(month=12, day=31)
        return dt(start), dt(end, end=True), 'This year', range_key

    if range_key == 'last_year':
        y = today.year - 1
        start = date(y, 1, 1)
        end = date(y, 12, 31)
        return dt(start), dt(end, end=True), 'Last year', range_key

    if range_key == 'ytd':
        start = today.replace(month=1, day=1)
        return dt(start), dt(today, end=True), 'Year to date', range_key

    if range_key == 'all':
        return None, None, 'All time', range_key

    # ---- custom ----
    try:
        start_d = datetime.strptime(request.GET.get('start', ''), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        start_d = today.replace(day=1)
    try:
        end_d = datetime.strptime(request.GET.get('end', ''), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        end_d = today

    return dt(start_d), dt(end_d, end=True), (
        f"{start_d.strftime('%d %b %Y')} → {end_d.strftime('%d %b %Y')}"
    ), 'custom'


def _bucket_for(start, end, range_key):
    """
    Decide whether to group by day/week/month/quarter.
    """
    if start is None or end is None:
        return 'month', TruncMonth('occurred_at')
    days = (end - start).days
    if days <= 1:
        return 'hour', None  # handled by caller
    if days <= 14:
        return 'day', TruncDay('occurred_at')
    if days <= 90:
        return 'week', TruncWeek('occurred_at')
    if days <= 800:
        return 'month', TruncMonth('occurred_at')
    return 'quarter', TruncQuarter('occurred_at')


# ============================================================
#  FINANCIAL DASHBOARD (ledger-based)
# ============================================================
@login_required
def finance_ledger(request):
    """
    Primary financial dashboard:
      • Filters (range presets + custom)
      • Revenue vs Expenses vs Profit KPIs
      • Time-series chart
      • Category / reason breakdown
      • Recent activity feed
    """
    org = _org(request)
    if org is None and not getattr(request.user, 'is_superadmin', False):
        messages.error(request, 'No organization linked to your account.')
        return redirect('dashboard')

    start_dt, end_dt, label, range_key = _resolve_range(request)

    qs = LedgerEntry.objects.filter(organization=org)
    if start_dt:
        qs = qs.filter(occurred_at__gte=start_dt)
    if end_dt:
        qs = qs.filter(occurred_at__lte=end_dt)

    # ---- KPI totals ----
    revenue = qs.filter(kind='revenue').aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    refunds = qs.filter(kind='refund').aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    expenses = qs.filter(kind='expense').aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    vat_collected = qs.filter(kind='revenue').aggregate(t=Sum('vat_amount'))['t'] or Decimal('0.00')

    net_revenue = revenue - refunds
    profit = net_revenue - expenses
    margin = (profit / net_revenue * 100) if net_revenue else Decimal('0')

    # ---- Chart series ----
    bucket, trunc = _bucket_for(start_dt, end_dt, range_key)

    if trunc is None:
        # hour bucketing for single-day
        rev_series = (
            qs.filter(kind='revenue')
            .extra(select={'h': "strftime('%%H', occurred_at)"})
            .values('h').annotate(total=Sum('amount')).order_by('h')
        )
        exp_series = (
            qs.filter(kind='expense')
            .extra(select={'h': "strftime('%%H', occurred_at)"})
            .values('h').annotate(total=Sum('amount')).order_by('h')
        )
        chart = {}
        for row in rev_series:
            chart[row['h']] = {'label': f"{row['h']}:00", 'revenue': float(row['total']), 'expenses': 0}
        for row in exp_series:
            chart.setdefault(row['h'], {'label': f"{row['h']}:00", 'revenue': 0, 'expenses': 0})
            chart[row['h']]['expenses'] = float(row['total'])
        chart_data = [chart[k] for k in sorted(chart)]
    else:
        rev_series = list(
            qs.filter(kind='revenue').annotate(bucket=trunc).values('bucket').annotate(total=Sum('amount')).order_by('bucket')
        )
        exp_series = list(
            qs.filter(kind='expense').annotate(bucket=trunc).values('bucket').annotate(total=Sum('amount')).order_by('bucket')
        )
        buckets = {}
        for row in rev_series:
            if row['bucket']:
                k = row['bucket']
                buckets.setdefault(k, {'label': _fmt_bucket(k, bucket), 'revenue': 0, 'expenses': 0})
                buckets[k]['revenue'] = float(row['total'])
        for row in exp_series:
            if row['bucket']:
                k = row['bucket']
                buckets.setdefault(k, {'label': _fmt_bucket(k, bucket), 'revenue': 0, 'expenses': 0})
                buckets[k]['expenses'] = float(row['total'])
        chart_data = [buckets[k] for k in sorted(buckets.keys())]

    chart_max = max(
        (max(p['revenue'], p['expenses']) for p in chart_data), default=0
    ) or 1

    # ---- Expense breakdown by reason / expense title ----
    expense_by_reason = list(
        qs.filter(kind='expense')
        .values('reason')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:8]
    )
    total_exp = sum((r['total'] or Decimal('0')) for r in expense_by_reason) or Decimal('1')
    for r in expense_by_reason:
        r['pct'] = round(float(r['total']) / float(total_exp) * 100, 1)

    # ---- Revenue by source ----
    revenue_by_source = list(
        qs.filter(kind='revenue')
        .values('source')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    source_labels = dict(LedgerEntry.SOURCE)

    # ---- Recent activity ----
    recent = list(qs.order_by('-occurred_at')[:15])

    # ---- Settings (for VAT display) ----
    settings = get_financial_settings(org)

    return render(request, 'bnb/finance_ledger.html', {
        'range_key': range_key,
        'range_label': label,
        'start_dt': start_dt,
        'end_dt': end_dt,
        'range_presets': RANGE_PRESETS,

        # KPIs
        'revenue': revenue,
        'refunds': refunds,
        'net_revenue': net_revenue,
        'expenses': expenses,
        'profit': profit,
        'margin': round(margin, 1),
        'vat_collected': vat_collected,

        # Chart
        'chart_data': chart_data,
        'chart_max': chart_max,
        'bucket': bucket,

        # Breakdowns
        'expense_by_reason': expense_by_reason,
        'revenue_by_source': revenue_by_source,
        'source_labels': source_labels,

        # Feed
        'recent': recent,

        # Settings
        'vat_enabled': bool(settings and settings.vat_enabled),
        'vat_label': settings.vat_label if settings else 'VAT',
    })


def _fmt_bucket(d, bucket):
    if bucket == 'day':
        return d.strftime('%d %b')
    if bucket == 'week':
        # week anchor is Monday
        return d.strftime('Wk %d %b')
    if bucket == 'quarter':
        q = (d.month - 1) // 3 + 1
        return f"Q{q} {d.year}"
    return d.strftime('%b %y')


@login_required
def finance_profit_ledger(request):
    """
    Profit & Loss statement styled as a traditional ledger book.
    Itemizes expenses by category/reason for a balance-sheet feel.
    """
    from datetime import datetime
    from django.db.models.functions import TruncMonth
    from django.db.models import Sum
    from decimal import Decimal
    from .models import LedgerEntry

    org = _org(request)
    if org is None:
        messages.error(request, 'No organization linked.')
        return redirect('dashboard')

    start_dt, end_dt, label, range_key = _resolve_range(request)

    # 1. Fetch all ledger entries in the date range
    entries_qs = LedgerEntry.objects.filter(organization=org)
    if start_dt:
        entries_qs = entries_qs.filter(occurred_at__gte=start_dt)
    if end_dt:
        entries_qs = entries_qs.filter(occurred_at__lt=end_dt)
    
    entries_qs = entries_qs.filter(kind__in=['revenue', 'expense', 'refund']).order_by('occurred_at')

    # 2. Group by Month
    months_dict = {}
    
    for entry in entries_qs:
        m_key = entry.occurred_at.strftime('%B %Y')
        if m_key not in months_dict:
            months_dict[m_key] = {
                'label': m_key,
                'revenues': {},
                'expenses': {},
                'refunds': Decimal('0'),
                'total_rev': Decimal('0'),
                'total_exp': Decimal('0'),
                'net_profit': Decimal('0'),
                'margin': 0.0,
            }
        
        m = months_dict[m_key]

        if entry.kind == 'revenue':
            # Group revenue by source (e.g. Booking, Manual)
            source = entry.get_source_display()
            if source not in m['revenues']:
                m['revenues'][source] = Decimal('0')
            m['revenues'][source] += entry.amount
            m['total_rev'] += entry.amount

        elif entry.kind == 'refund':
            m['refunds'] += entry.amount
            m['total_rev'] -= entry.amount
            
        elif entry.kind == 'expense':
            # Group expenses by their specific reason (e.g. "House cleaning — Cleaning")
            # We clean up the string to just show the main part if it's too long
            reason = entry.reason or 'Uncategorised'
            if ' — ' in reason:
                # If it's "House cleaning — Cleaning", just show "House cleaning"
                reason = reason.split(' — ')[0]
                
            if reason not in m['expenses']:
                m['expenses'][reason] = Decimal('0')
            m['expenses'][reason] += entry.amount
            m['total_exp'] += entry.amount

    # 3. Calculate Totals & Margins
    ledger = []
    overall_rev = Decimal('0')
    overall_exp = Decimal('0')
    running_balance = Decimal('0')

    for m_key, m in months_dict.items():
        m['net_profit'] = m['total_rev'] - m['total_exp']
        running_balance += m['net_profit']
        
        if m['total_rev'] > 0:
            m['margin'] = round(float(m['net_profit'] / m['total_rev'] * 100), 1)
        else:
            m['margin'] = 0.0
            
        m['running_balance'] = running_balance
        m['is_profitable'] = m['net_profit'] >= 0
        
        # Convert dictionaries to sorted lists for the template
        m['revenues_list'] = [{'name': k, 'amount': v} for k, v in sorted(m['revenues'].items(), key=lambda x: x[1], reverse=True)]
        m['expenses_list'] = [{'name': k, 'amount': v} for k, v in sorted(m['expenses'].items(), key=lambda x: x[1], reverse=True)]

        overall_rev += m['total_rev']
        overall_exp += m['total_exp']
        
        ledger.append(m)

    overall_profit = overall_rev - overall_exp
    overall_margin = round(float(overall_profit / overall_rev * 100), 1) if overall_rev else 0.0

    return render(request, 'bnb/finance_profit_ledger.html', {
        'range_key': range_key,
        'range_label': label,
        'range_presets': RANGE_PRESETS,
        
        'ledger': ledger,
        
        'total_rev': overall_rev,
        'total_exp': overall_exp,
        'total_profit': overall_profit,
        'overall_margin': overall_margin,
        'closing_balance': running_balance,
    })


# ============================================================
#  SETTINGS — VAT TOGGLE
# ============================================================
@login_required
def finance_settings(request):
    """Let org admins toggle VAT on/off and set the rate."""
    org = _org(request)
    if org is None:
        messages.error(request, 'No organization linked.')
        return redirect('dashboard')

    settings = get_financial_settings(org)

    if request.method == 'POST':
        settings.vat_enabled = request.POST.get('vat_enabled') == '1'
        try:
            settings.vat_rate = Decimal(request.POST.get('vat_rate') or '0')
        except Exception:
            settings.vat_rate = Decimal('0')
        settings.vat_label = request.POST.get('vat_label') or 'VAT'
        settings.vat_inclusive = request.POST.get('vat_inclusive') == '1'
        settings.save()
        messages.success(request, 'Financial settings saved.')
        return redirect('bnb_finance_settings')

    return render(request, 'bnb/finance_settings.html', {
        'settings': settings,
    })
    
    
    
# ============================================================
#  HELPERS
# ============================================================
def _require_bnb(request):
    org = getattr(request.user, 'organization', None)
    return (
        bool(org and org.org_type in ('bnb', 'mixed'))
        or getattr(request.user, 'is_superadmin', False)
    )


def _org(request):
    return getattr(request.user, 'organization', None)


def _log(request, action, details=''):
    try:
        ActivityLog.objects.create(
            organization=_org(request),
            user=request.user,
            action=action,
            details=details,
        )
    except Exception:
        pass


# ============================================================
#  MARKETPLACE CATEGORY SEEDING
# ============================================================
DEFAULT_MARKETPLACE_CATEGORIES = [
    # slug,        name,       icon,     accent,    display_order
    ('stays',      'Stays',    'bed',    'indigo',  10),
]


def _ensure_default_categories():
    """
    Idempotent: ensure the default ListingCategory rows exist.

    Safe to call on every request — get_or_create is a fast, indexed
    lookup after the first call. Wrapped in try/except so a broken
    marketplace app never takes down the BnB views.
    """
    try:
        from marketplace.models import ListingCategory
        for slug, name, icon, accent, order in DEFAULT_MARKETPLACE_CATEGORIES:
            ListingCategory.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'icon': icon,
                    'accent': accent,
                    'display_order': order,
                },
            )
    except Exception:
        pass


# ============================================================
#  DASHBOARD
# ============================================================
@login_required
def bnb_dashboard(request):
    if not _require_bnb(request):
        messages.error(request, 'BnB module not available for your organization.')
        return redirect('dashboard')

    _ensure_default_categories()

    org = _org(request)
    today = timezone.now().date()
    month_start = today.replace(day=1)

    props = (
        Property.objects.filter(organization=org)
        if org else Property.objects.none()
    )
    bookings = (
        Booking.objects
        .filter(property__organization=org)
        .select_related('property', 'guest')
        if org else Booking.objects.none()
    )

    # ---------- Finance ----------
    total_revenue = bookings.filter(
        status__in=['confirmed', 'checked_in', 'checked_out']
    ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')

    month_revenue = bookings.filter(
        status__in=['confirmed', 'checked_in', 'checked_out'],
        created_at__date__gte=month_start,
    ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')

    total_expenses = (
        Expense.objects.filter(organization=org)
        .aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    )
    month_expenses = (
        Expense.objects.filter(organization=org, expense_date__gte=month_start)
        .aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    )

    profit = total_revenue - total_expenses
    profit_margin = (profit / total_revenue * 100) if total_revenue else 0

    # ---------- Occupancy ----------
    total_props = props.count()
    occupied_props = bookings.filter(
        check_in__lte=today, check_out__gt=today,
        status__in=['confirmed', 'checked_in'],
    ).values('property').distinct().count()
    occupancy_rate = (occupied_props / total_props * 100) if total_props else 0

    # ---------- Pending approvals ----------
    pending_bookings_count = bookings.filter(status='pending').count()

    # ---------- Today's activity ----------
    checkins_today = bookings.filter(
        check_in=today,
        status__in=['confirmed', 'checked_in'],
    ).count()

    checkouts_today = bookings.filter(
        check_out=today,
        status__in=['checked_in', 'checked_out'],
    ).count()

    # ---------- Revenue split ----------
    paid_total = (
        bookings.filter(
            status__in=['confirmed', 'checked_in', 'checked_out'],
            amount_paid__gt=0,
        )
        .aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')
    )
    unpaid_total = max(total_revenue - paid_total, Decimal('0.00'))

    # ---------- Marketplace engagement ----------
    marketplace_stats = {
        'total_views': 0,
        'total_saves': 0,
        'total_reviews': 0,
        'total_bookings': 0,
        'avg_rating': 0,
        'total_pending_approvals': 0,
    }
    listings_recent = []
    notifications_unread = 0

    try:
        from marketplace.models import Listing
        listings_recent = (
            Listing.objects.filter(organization=org)
            .order_by('-updated_at')[:6]
        )
        agg = (
            Listing.objects
            .filter(organization=org)
            .aggregate(
                views=Sum('view_count'),
                saves=Sum('wishlist_count'),
                reviews=Sum('review_count'),
                bookings=Sum('booking_count'),
                rating=Avg('average_rating'),
            )
        )
        marketplace_stats = {
            'total_views':    agg['views'] or 0,
            'total_saves':    agg['saves'] or 0,
            'total_reviews':  agg['reviews'] or 0,
            'total_bookings': agg['bookings'] or 0,
            'avg_rating':     round(float(agg['rating'] or 0), 1),
            'total_pending_approvals': 0,
        }
    except Exception:
        pass

    # ---------- Guest bookings from marketplace ----------
    pending_marketplace_count = 0
    pay_later_count = 0

    try:
        from guestaccount.models import GuestBooking
        gb_qs = GuestBooking.objects.filter(organization=org)
        pending_marketplace_count = gb_qs.filter(status='pending').count()
        pay_later_count = gb_qs.filter(
            payment_policy__in=[
                'pay_on_arrival', 'pay_on_delivery', 'pay_on_completion',
            ],
            status__in=['pending', 'confirmed', 'in_progress'],
        ).count()

        marketplace_stats['total_pending_approvals'] = pending_marketplace_count
    except Exception:
        pass

    # ---------- Notifications ----------
    try:
        from notifications.models import NotificationLog
        notifications_unread = NotificationLog.objects.filter(
            recipient_organization=org,
            read_at__isnull=True,
        ).count()
    except Exception:
        pass

    # ---------- Pagination for "Recent bookings" ----------
    bookings_ordered = bookings.order_by('-created_at')
    bookings_paginator = Paginator(bookings_ordered, 10)
    bookings_page = bookings_paginator.get_page(request.GET.get('bookings_page'))

    # ---------- Final context ----------
    context = {
        # Properties / bookings
        'properties': props,
        'bookings': bookings_page.object_list,
        'bookings_page': bookings_page,
        'bookings_paginator': bookings_paginator,
        'props_count': props.count(),
        'bookings_count': bookings.count(),
        'pending_bookings_count': pending_bookings_count,

        # Operations
        'open_tasks': (
            HousekeepingTask.objects
            .filter(property__organization=org)
            .exclude(status='done').count()
            if org else 0
        ),
        'open_maintenance': (
            MaintenanceRequest.objects
            .filter(property__organization=org)
            .exclude(status='resolved').count()
            if org else 0
        ),

        # Finance
        'total_revenue': total_revenue,
        'month_revenue': month_revenue,
        'total_expenses': total_expenses,
        'month_expenses': month_expenses,
        'profit': profit,
        'profit_margin': round(profit_margin, 1),
        'paid_total': paid_total,
        'unpaid_total': unpaid_total,

        # Occupancy
        'occupancy_rate': round(occupancy_rate, 1),
        'occupied_props': occupied_props,

        # Today
        'checkins_today': checkins_today,
        'checkouts_today': checkouts_today,

        # Upcoming / recent
        'upcoming_checkins': bookings.filter(
            check_in__gte=today, status__in=['pending', 'confirmed']
        ).order_by('check_in')[:6],

        'recent_reviews': (
            Review.objects.filter(organization=org)
            .select_related('property')
            .order_by('-review_date')[:4]
            if org else []
        ),

        # Marketplace
        'listings_recent': listings_recent,
        'notifications_unread': notifications_unread,
        'marketplace_stats': marketplace_stats,

        # Guest-account (banner count only)
        'pending_marketplace_count': pending_marketplace_count,
        'pay_later_count': pay_later_count,
    }
    return render(request, 'bnb/dashboard.html', context)


# ============================================================
#  NOTIFICATIONS INBOX
# ============================================================
@login_required
def notifications_inbox(request):
    org = _org(request)
    items = []
    unread_count = 0
    try:
        from notifications.models import NotificationLog
        qs = NotificationLog.objects.filter(
            recipient_organization=org,
        ).order_by('-created_at')
        unread_count = qs.filter(read_at__isnull=True).count()
        items = qs[:200]
    except Exception:
        pass
    return render(request, 'bnb/notifications_inbox.html', {
        'items': items,
        'unread_count': unread_count,
        'organization': org,
    })


@login_required
def notification_mark_read(request, notification_id):
    org = _org(request)
    try:
        from notifications.models import NotificationLog
        notif = NotificationLog.objects.filter(
            id=notification_id,
            recipient_organization=org,
        ).first()
        if notif:
            notif.mark_read()
    except Exception:
        pass
    return redirect('bnb_notifications_inbox')


@login_required
def notification_mark_all_read(request):
    org = _org(request)
    try:
        from notifications.models import NotificationLog
        from django.utils import timezone as _tz
        NotificationLog.objects.filter(
            recipient_organization=org,
            read_at__isnull=True,
        ).update(status='read', read_at=_tz.now())
        messages.success(request, 'All notifications marked as read.')
    except Exception:
        messages.warning(request, 'Could not mark notifications as read.')
    return redirect('bnb_notifications_inbox')


# ============================================================
#  PROPERTIES — LIST
# ============================================================
# Categories that legitimately belong to the BnB module. Any marketplace
# category NOT in this list (tours, food, laundry, transport, …) is
# explicitly excluded so BnB stays purely stays.
BNB_ALLOWED_CATEGORY_SLUGS = tuple(
    slug for slug, *_ in DEFAULT_MARKETPLACE_CATEGORIES
)


@login_required
def property_list(request):
    """
    Paginated list of BnB properties with search, category filter,
    publication-state filter and a simple sort.

    Only categories that belong to the BnB module are exposed as chips.
    Other marketplace categories (tours, food, laundry, transport, …)
    are excluded so the list stays BnB-only.
    """
    org = _org(request)
    q = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '').strip()
    state = request.GET.get('state', '').strip()
    sort = request.GET.get('sort', 'newest').strip()

    props = (
        Property.objects.filter(organization=org)
        .select_related('category', 'listing')
        if org else Property.objects.none()
    )

    # ---- Search ----
    if q:
        props = props.filter(
            Q(name__icontains=q) |
            Q(location_label__icontains=q) |
            Q(address__icontains=q)
        )

    # ---- Category filter (only BnB categories) ----
    if category_slug:
        if category_slug in BNB_ALLOWED_CATEGORY_SLUGS:
            props = props.filter(category__slug=category_slug)
        else:
            # Non-BnB category requested — return nothing so it's clear
            props = props.none()

    # ---- Publication-state filter ----
    if state == 'live':
        props = props.filter(
            listing__isnull=False,
            listing__status='approved',
            listing__is_active=True,
        )
    elif state == 'pending':
        props = props.filter(listing__isnull=False, listing__status='pending')
    elif state == 'hidden':
        props = props.filter(
            listing__isnull=False,
            listing__status='approved',
            listing__is_active=False,
        )
    elif state == 'draft':
        props = props.filter(listing__isnull=True)

    # ---- Sort ----
    sort_map = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'name':   'name',
    }
    props = props.order_by(sort_map.get(sort, '-created_at'))

    # ---- Pagination ----
    paginator = Paginator(props, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    # ---- Category chips (BnB-only) ----
    categories = []
    try:
        from marketplace.models import ListingCategory
        categories = list(
            ListingCategory.objects
            .filter(slug__in=BNB_ALLOWED_CATEGORY_SLUGS)
            .order_by('display_order', 'name')
        )
    except Exception:
        categories = []

    return render(request, 'bnb/property_list.html', {
        'properties': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'q': q,
        'category_slug': category_slug,
        'state': state,
        'sort': sort,
        'categories': categories,
    })


# ============================================================
#  PROPERTIES — DETAIL
# ============================================================
@login_required
def property_detail(request, property_id):
    """
    Single-property view (BnB only).

    Focus: this property's identity, status, contact, availability, and
    its own recent bookings. No org-wide revenue/occupancy numbers.
    """
    org = _org(request)
    prop = get_object_or_404(
        Property.objects.select_related('category', 'listing'),
        id=property_id, organization=org,
    )

    today = timezone.now().date()

    # ---- Bookings scoped to this property ----
    bookings_qs = (
        Booking.objects
        .filter(property=prop)
        .select_related('guest')
        .order_by('-created_at')
    )

    total_bookings = bookings_qs.count()
    confirmed_bookings = bookings_qs.filter(
        status__in=['confirmed', 'checked_in', 'checked_out']
    ).count()
    pending_bookings = bookings_qs.filter(status='pending').count()

    # ---- Current active booking (if any) ----
    current_booking = bookings_qs.filter(
        check_in__lte=today,
        check_out__gt=today,
        status__in=['confirmed', 'checked_in'],
    ).first()
    is_occupied_now = current_booking is not None

    # ---- Paginated recent bookings ----
    paginator = Paginator(bookings_qs, 10)
    page_obj = paginator.get_page(request.GET.get('bookings_page'))

    # ---- Marketplace state ----
    listing = prop.listing if prop.listing_id else None

    # ---- Per-property marketplace engagement ----
    marketplace_stats = {
        'views': 0,
        'saves': 0,
        'reviews': 0,
        'rating': 0,
    }
    if listing:
        try:
            marketplace_stats = {
                'views':   listing.view_count or 0,
                'saves':   listing.wishlist_count or 0,
                'reviews': listing.review_count or 0,
                'rating':  round(float(listing.average_rating or 0), 1),
            }
        except Exception:
            pass

    # ---- Upcoming availability blocks (next 3) ----
    upcoming_blocks = []
    try:
        upcoming_blocks = list(
            listing.availability_blocks
            .filter(
                status__in=['pending', 'confirmed'],
                end_date__gte=today,
            )
            .order_by('start_date')[:3]
        ) if listing else []
    except Exception:
        upcoming_blocks = []

    context = {
        'property': prop,
        'listing': listing,
        'bookings': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,

        # Stats (this property only)
        'total_bookings': total_bookings,
        'confirmed_bookings': confirmed_bookings,
        'pending_bookings': pending_bookings,
        'is_occupied_now': is_occupied_now,
        'current_booking': current_booking,

        # Marketplace
        'marketplace_stats': marketplace_stats,

        # Availability
        'upcoming_blocks': upcoming_blocks,
    }
    return render(request, 'bnb/property_detail.html', context)


# ============================================================
#  PROPERTIES — ADD
# ============================================================
@login_required
def property_add(request):
    _ensure_default_categories()
    org = _org(request)

    if request.method == 'POST':
        # Pre-build the instance WITH the org attached, so __init__ can
        # filter amenities by org from the very first render.
        instance = Property(organization=org)
        form = PropertyForm(request.POST, request.FILES, instance=instance)

        if form.is_valid():
            publish = form.cleaned_data.get('publish_to_marketplace', True)

            prop = form.save(commit=False)
            prop.organization = org
            prop.save()

            if publish:
                listing = _publish_property(prop, auto_approve=True)
                if listing:
                    messages.success(
                        request,
                        f'"{prop.name}" has been added and is now live on the marketplace.',
                    )
                else:
                    messages.warning(
                        request,
                        f'"{prop.name}" was added but could not be published '
                        'to the marketplace. Please check the logs.',
                    )
            else:
                messages.success(
                    request,
                    f'"{prop.name}" has been added (not published to the marketplace).',
                )

            _log(request, 'Added property', prop.name)
            return redirect('bnb_property_list')
    else:
        # Same on GET — build the instance with org so __init__ sees it.
        instance = Property(organization=org)
        form = PropertyForm(instance=instance)

    return render(request, 'bnb/property_form.html', {
        'form': form,
        'mode': 'create',
        'publish_default': True,
    })


@login_required
def property_edit(request, property_id):
    _ensure_default_categories()
    prop = get_object_or_404(
        Property, id=property_id, organization=_org(request),
    )

    try:
        initially_published = bool(
            prop.listing_id and prop.listing.status == 'approved' and prop.listing.is_active
        )
    except Exception:
        initially_published = False

    if request.method == 'POST':
        form = PropertyForm(request.POST, request.FILES, instance=prop)
        if form.is_valid():
            publish = form.cleaned_data.get('publish_to_marketplace', True)
            form.save()

            if publish:
                listing = _publish_property(prop, auto_approve=True)
                if listing:
                    messages.success(
                        request,
                        f'"{prop.name}" was updated and is live on the marketplace.',
                    )
                else:
                    messages.warning(
                        request,
                        f'"{prop.name}" was updated but could not be published '
                        'to the marketplace. Please check the logs.',
                    )
            else:
                if prop.listing_id:
                    try:
                        prop.listing.status = 'unpublished'
                        prop.listing.is_active = False
                        prop.listing.save(update_fields=['status', 'is_active'])
                        messages.success(
                            request,
                            f'"{prop.name}" was updated and removed from the marketplace.',
                        )
                    except Exception:
                        messages.warning(
                            request,
                            f'"{prop.name}" was updated, but the marketplace '
                            'listing could not be unpublished.',
                        )
                else:
                    messages.success(
                        request,
                        f'"{prop.name}" was updated (never published to the marketplace).',
                    )

            _log(request, 'Edited property', prop.name)
            return redirect('bnb_property_list')
    else:
        form = PropertyForm(instance=prop, initial={
            'publish_to_marketplace': initially_published,
        })

    return render(request, 'bnb/property_form.html', {
        'form': form,
        'mode': 'edit',
        'property': prop,
        'publish_default': initially_published,
    })


@login_required
def property_publish_toggle(request, property_id):
    prop = get_object_or_404(
        Property, id=property_id, organization=_org(request),
    )

    if not prop.listing_id:
        listing = _publish_property(prop, auto_approve=True)
        if listing:
            messages.success(request, f'"{prop.name}" is now live on the marketplace.')
        else:
            messages.error(request, f'Could not publish "{prop.name}".')
        _log(request, 'Published property', prop.name)
        return redirect('bnb_property_list')

    listing = prop.listing

    if listing.status == 'approved' and listing.is_active:
        listing.status = 'unpublished'
        listing.is_active = False
        listing.save(update_fields=['status', 'is_active', 'updated_at'])
        messages.success(request, f'"{prop.name}" is now hidden from the marketplace.')
        _log(request, 'Unpublished property', prop.name)
    else:
        _publish_property(prop, auto_approve=True)
        messages.success(request, f'"{prop.name}" is now live on the marketplace.')
        _log(request, 'Published property', prop.name)

    return redirect('bnb_property_list')


@login_required
def property_delete(request, property_id):
    prop = get_object_or_404(
        Property, id=property_id, organization=_org(request),
    )
    if request.method == 'POST':
        name = prop.name
        if prop.listing_id:
            try:
                prop.listing.is_active = False
                prop.listing.status = 'unpublished'
                prop.listing.save(update_fields=['is_active', 'status'])
            except Exception:
                pass
        prop.delete()
        _log(request, 'Deleted property', name)
        messages.success(request, 'Property deleted (marketplace listing unpublished).')
    return redirect('bnb_property_list')


# ============================================================
#  BOOKINGS — LIST
# ============================================================
@login_required
def booking_list(request):
    org = _org(request)
    status = request.GET.get('status', '').strip()
    q = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'newest').strip()

    base_qs = (
        Booking.objects
        .filter(property__organization=org)
        .select_related('property', 'guest', 'guest_booking')
        if org else Booking.objects.none()
    )
    pending_count = base_qs.filter(status='pending').count()

    bookings = base_qs

    # ---- Status filter ----
    if status:
        bookings = bookings.filter(status=status)

    # ---- Search ----
    if q:
        bookings = bookings.filter(
            Q(guest_name__icontains=q) |
            Q(guest_email__icontains=q) |
            Q(guest_phone__icontains=q) |
            Q(property__name__icontains=q)
        )

    # ---- Sort ----
    sort_map = {
        'newest':   '-created_at',
        'oldest':   'created_at',
        'checkin':  'check_in',
        'amount':   '-total_amount',
    }
    bookings = bookings.order_by(sort_map.get(sort, '-created_at'))

    # ---- Pagination (20 per page) ----
    paginator = Paginator(bookings, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'bnb/booking_list.html', {
        'bookings': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'status': status,
        'q': q,
        'sort': sort,
        'pending_count': pending_count,
        'booking_statuses': Booking.STATUS,
    })


# ============================================================
#  BOOKINGS — DETAIL
# ============================================================
@login_required
def booking_detail(request, booking_id):
    from datetime import date

    booking = get_object_or_404(
        Booking.objects.select_related('property', 'guest', 'guest_booking'),
        id=booking_id, property__organization=_org(request),
    )

    # ---- Marketplace linkage ----
    guest_booking = booking.guest_booking
    payment_attempts = []
    receipts = []
    if guest_booking:
        try:
            payment_attempts = guest_booking.payment_attempts.all()
        except Exception:
            payment_attempts = []
        try:
            receipts = guest_booking.receipts.all()
        except Exception:
            receipts = []

    # ---- Context-aware action flags ----
    status = booking.status
    can_confirm    = status == 'pending'
    can_check_in   = status == 'confirmed'
    can_check_out  = status == 'checked_in'
    can_cancel     = status in ('pending', 'confirmed')
    can_delete     = status in ('cancelled', 'no_show', 'checked_out')

    # ---- Days until check-in ----
    nights_until_checkin = None
    if booking.check_in:
        nights_until_checkin = (booking.check_in - date.today()).days

    # ---- Nightly rate (best-effort) ----
    nightly_rate = None
    if booking.nights and booking.total_amount:
        try:
            nightly_rate = (booking.total_amount / booking.nights).quantize(Decimal('0.01'))
        except Exception:
            nightly_rate = None

    return render(request, 'bnb/booking_detail.html', {
        'booking': booking,
        'payments': booking.payments.all(),
        'invoices': booking.invoices.all(),
        'guest_booking': guest_booking,
        'payment_attempts': payment_attempts,
        'receipts': receipts,
        'can_confirm': can_confirm,
        'can_check_in': can_check_in,
        'can_check_out': can_check_out,
        'can_cancel': can_cancel,
        'can_delete': can_delete,
        'nights_until_checkin': nights_until_checkin,
        'nightly_rate': nightly_rate,
    })


@login_required
def booking_add(request):
    messages.error(
        request,
        'Bookings can only be created by guests through the marketplace. '
        'Approve or decline them from the Bookings list.',
    )
    return redirect('bnb_booking_list')


@login_required
def booking_edit(request, booking_id):
    booking = get_object_or_404(
        Booking, id=booking_id, property__organization=_org(request),
    )
    messages.info(
        request,
        'To change a booking, use the status buttons on the booking page.',
    )
    return redirect('bnb_booking_detail', booking_id=booking.id)


@login_required
def booking_delete(request, booking_id):
    booking = get_object_or_404(
        Booking, id=booking_id, property__organization=_org(request),
    )
    if request.method == 'POST':
        try:
            _release_listing_for_booking(booking)
        except Exception:
            pass
        booking.delete()
        messages.success(request, 'Booking deleted and dates released.')
    return redirect('bnb_booking_list')


@login_required
def booking_status_update(request, booking_id, new_status):
    booking = get_object_or_404(
        Booking, id=booking_id, property__organization=_org(request),
    )
    valid = dict(Booking.STATUS)
    if new_status not in valid:
        messages.error(request, 'Invalid status.')
        return redirect('bnb_booking_detail', booking_id=booking.id)

    old_status = booking.status
    booking.status = new_status
    booking.save()

    _log(
        request,
        f'Booking status: {old_status} → {new_status}',
        f'{booking.guest_name} @ {booking.property.name}',
    )

    messages.success(
        request,
        f'Booking for {booking.guest_name} marked as '
        f'{dict(Booking.STATUS)[new_status]}.',
    )
    return redirect('bnb_booking_detail', booking_id=booking.id)


# ============================================================
#  BOOKINGS — CALENDAR
# ============================================================
@login_required
def booking_calendar(request):
    from datetime import date, timedelta
    from calendar import monthrange

    org = _org(request)

    # ---- Query params ----
    try:
        year = int(request.GET.get('year', 0))
        month = int(request.GET.get('month', 0))
        if not (1 <= year <= 9999) or not (1 <= month <= 12):
            raise ValueError
    except (TypeError, ValueError):
        today = timezone.now().date()
        year, month = today.year, today.month

    first_of_month = date(year, month, 1)
    last_of_month = date(year, month, monthrange(year, month)[1])

    # ---- Bookings to show ----
    bookings = (
        Booking.objects
        .filter(property__organization=org)
        .exclude(status='cancelled')
        .select_related('property')
        .order_by('check_in')
    ) if org else Booking.objects.none()

    # ---- Per-property color map (stable across the page) ----
    property_ids = list(
        bookings.values_list('property_id', 'property__name')
        .distinct()
        .order_by('property__name')
    )
    # Deduplicate (values_list can repeat ids when names are grouped)
    seen_ids = set()
    properties_ordered = []
    for pid, pname in property_ids:
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            properties_ordered.append((pid, pname))

    palette = [
        '#0ea5e9', '#10b981', '#f59e0b', '#8b5cf6',
        '#ef4444', '#14b8a6', '#f97316', '#6366f1',
        '#84cc16', '#ec4899',
    ]
    color_map = {}
    for i, (pid, _pname) in enumerate(properties_ordered):
        color_map[pid] = palette[i % len(palette)]

    # ---- Build the month grid (6 rows × 7 cols) ----
    # Start on the Monday on/before the 1st
    start_offset = first_of_month.weekday()  # Mon=0, Sun=6
    grid_start = first_of_month - timedelta(days=start_offset)
    # End on the Sunday on/after the last day
    end_offset = 6 - last_of_month.weekday()
    grid_end = last_of_month + timedelta(days=end_offset)

    today = timezone.now().date()

    # Pre-fetch bookings into a list to iterate cheaply per day
    booking_list = list(bookings)

    weeks = []
    current_week = []
    day = grid_start
    while day <= grid_end:
        day_bookings = [
            b for b in booking_list
            if b.check_in <= day <= b.check_out
        ]
        current_week.append({
            'date': day,
            'in_month': (day.month == month),
            'is_today': (day == today),
            'is_weekend': (day.weekday() >= 5),
            'bookings': day_bookings,
        })
        if len(current_week) == 7:
            weeks.append(current_week)
            current_week = []
        day += timedelta(days=1)
    if current_week:
        weeks.append(current_week)

    # ---- Navigation URLs ----
    def _shift_month(y, m, delta):
        """Return (year, month) after shifting by delta months."""
        total = y * 12 + (m - 1) + delta
        return total // 12, (total % 12) + 1

    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, 1)
    today_year, today_month = today.year, today.month

    prev_url = f"?year={prev_year}&month={prev_month}"
    next_url = f"?year={next_year}&month={next_month}"
    this_url = f"?year={today_year}&month={today_month}"

    # ---- Summary: bookings per property (this month) ----
    month_bookings = [
        b for b in booking_list
        if b.check_in <= last_of_month and b.check_out >= first_of_month
    ]

    property_summary = []
    for pid, pname in properties_ordered:
        count = sum(1 for b in month_bookings if b.property_id == pid)
        if count:
            property_summary.append({
                'id': pid,
                'name': pname,
                'count': count,
                'color': color_map.get(pid, '#94a3b8'),
            })
    property_summary.sort(key=lambda x: -x['count'])

    # ---- Summary: bookings per status (this month) ----
    status_counts = {}
    for b in month_bookings:
        status_counts[b.status] = status_counts.get(b.status, 0) + 1
    status_summary = [
        {'key': k, 'label': dict(Booking.STATUS).get(k, k.title()), 'count': v}
        for k, v in status_counts.items()
    ]
    status_summary.sort(key=lambda x: -x['count'])

    # ---- Month labels ----
    month_name = first_of_month.strftime('%B %Y')
    today_month_label = today.strftime('%B %Y')

    context = {
        'year': year,
        'month': month,
        'month_name': month_name,
        'today_month_label': today_month_label,
        'is_current_month': (year == today.year and month == today.month),
        'weeks': weeks,
        'weekday_labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'prev_url': prev_url,
        'next_url': next_url,
        'this_url': this_url,

        'color_map': color_map,
        'properties_ordered': properties_ordered,
        'property_summary': property_summary,
        'status_summary': status_summary,

        'month_bookings_count': len(month_bookings),
        'total_bookings_count': len(booking_list),

        'list_bookings': booking_list,
    }
    return render(request, 'bnb/booking_calendar.html', context)


# ============================================================
#  GUESTS — LIST
# ============================================================
@login_required
def guest_list(request):
    org = _org(request)
    q = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'name').strip()
    today = timezone.now().date()
    month_start = today.replace(day=1)

    base_qs = (
        Guest.objects.filter(organization=org)
        if org else Guest.objects.none()
    )

    # ---- Headline counts (from base, before filters) ----
    total_guests      = base_qs.count()
    repeat_guests     = base_qs.filter(total_stays__gte=2).count()
    blacklisted_count = base_qs.filter(is_blacklisted=True).count()
    new_this_month    = base_qs.filter(created_at__date__gte=month_start).count()

    # ---- Filters ----
    guests = base_qs

    if q:
        guests = guests.filter(
            Q(full_name__icontains=q) |
            Q(email__icontains=q) |
            Q(phone__icontains=q) |
            Q(country__icontains=q)
        )

    # ---- Sort ----
    sort_map = {
        'name':       'full_name',
        'name_desc':  '-full_name',
        'stays':      '-total_stays',
        'spent':      '-total_spent',
        'newest':     '-created_at',
    }
    guests = guests.order_by(sort_map.get(sort, 'full_name'))

    # ---- Pagination (20 per page) ----
    paginator = Paginator(guests, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'bnb/guest_list.html', {
        'guests':             page_obj.object_list,
        'page_obj':           page_obj,
        'paginator':          paginator,

        'total_guests':       total_guests,
        'repeat_guests':      repeat_guests,
        'blacklisted_count':  blacklisted_count,
        'new_this_month':     new_this_month,

        'q':                  q,
        'sort':               sort,
    })


# ============================================================
#  GUESTS — DETAIL
# ============================================================
@login_required
def guest_detail(request, guest_id):
    from decimal import Decimal

    guest = get_object_or_404(
        Guest.objects.select_related('organization', 'user'),
        id=guest_id, organization=_org(request),
    )

    # ---- All bookings for this guest (prefetches property) ----
    bookings_qs = (
        guest.bookings
        .select_related('property')
        .order_by('-check_in')
    )
    bookings = list(bookings_qs)

    # ---- Aggregated stats ----
    total_stays = len(bookings)

    total_nights = sum(b.nights or 0 for b in bookings)

    total_spent = sum(
        (b.amount_paid or Decimal('0.00')) for b in bookings
        if b.status in ('confirmed', 'checked_in', 'checked_out')
    )
    if total_spent == 0:
        # Fall back to total_amount when nothing is marked paid
        total_spent = sum(
            (b.total_amount or Decimal('0.00')) for b in bookings
            if b.status in ('confirmed', 'checked_in', 'checked_out')
        )

    avg_spend = (
        (total_spent / total_stays).quantize(Decimal('0.01'))
        if total_stays else Decimal('0.00')
    )

    # ---- First / last stay dates ----
    valid_checkins = [b.check_in for b in bookings if b.check_in]
    first_stay = min(valid_checkins) if valid_checkins else None
    last_stay  = max(valid_checkins) if valid_checkins else None

    # ---- Bookings per property ----
    by_property = {}
    for b in bookings:
        pid = b.property_id
        if not pid:
            continue
        entry = by_property.setdefault(pid, {
            'name': b.property.name,
            'count': 0,
            'revenue': Decimal('0.00'),
        })
        entry['count'] += 1
        if b.status in ('confirmed', 'checked_in', 'checked_out'):
            entry['revenue'] += (b.amount_paid or Decimal('0.00'))

    bookings_by_property = sorted(
        [
            {'id': pid, **entry}
            for pid, entry in by_property.items()
        ],
        key=lambda x: -x['count'],
    )

    # Max count for bar-width ratios
    max_count = max((p['count'] for p in bookings_by_property), default=1)

    # ---- Loyalty flag ----
    is_loyal = total_stays >= 3

    return render(request, 'bnb/guest_detail.html', {
        'guest': guest,
        'bookings': bookings,

        'total_stays': total_stays,
        'total_nights': total_nights,
        'total_spent': total_spent,
        'avg_spend': avg_spend,
        'first_stay': first_stay,
        'last_stay': last_stay,

        'bookings_by_property': bookings_by_property,
        'max_count': max_count,
        'is_loyal': is_loyal,
    })


@login_required
def guest_add(request):
    if request.method == 'POST':
        form = GuestForm(request.POST)
        if form.is_valid():
            g = form.save(commit=False)
            g.organization = _org(request)
            g.save()
            messages.success(request, 'Guest added.')
            return redirect('bnb_guest_list')
    else:
        form = GuestForm()
    return render(request, 'bnb/guest_form.html', {'form': form})


@login_required
def guest_edit(request, guest_id):
    guest = get_object_or_404(Guest, id=guest_id, organization=_org(request))
    if request.method == 'POST':
        form = GuestForm(request.POST, instance=guest)
        if form.is_valid():
            form.save()
            messages.success(request, 'Guest updated.')
            return redirect('bnb_guest_list')
    else:
        form = GuestForm(instance=guest)
    return render(request, 'bnb/guest_form.html', {'form': form, 'guest': guest})


# ============================================================
#  HOUSEKEEPING — LIST
# ============================================================
@login_required
def housekeeping_list(request):
    org = _org(request)
    status = request.GET.get('status', '').strip()
    priority = request.GET.get('priority', '').strip()
    q = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'priority').strip()

    # Ensure local timezone for "Done today" calculation
    now_local = timezone.localtime()
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    base_qs = (
        HousekeepingTask.objects
        .filter(property__organization=org)
        .select_related('property')
        if org else HousekeepingTask.objects.none()
    )

    # ---- Headline counts ----
    open_count        = base_qs.filter(status='open').count()
    in_progress_count = base_qs.filter(status='in_progress').count()
    done_today_count  = base_qs.filter(
        status='done',
        completed_at__gte=today_start,
    ).count()

    # Overdue: open/in_progress tasks whose scheduled_for is in the past
    overdue_count = base_qs.filter(
        status__in=['open', 'in_progress'],
        scheduled_for__lt=now_local,
    ).count()

    # ---- Apply filters ----
    tasks = base_qs
    if status:
        tasks = tasks.filter(status=status)
    if priority:
        tasks = tasks.filter(priority=priority)
    if q:
        tasks = tasks.filter(
            Q(description__icontains=q) |
            Q(assigned_to__icontains=q) |
            Q(property__name__icontains=q)
        )

    # ---- Sort ----
    priority_order = models.Case(
        models.When(priority='urgent', then=0),
        models.When(priority='high',   then=1),
        models.When(priority='normal', then=2),
        models.When(priority='low',    then=3),
        default=4,
        output_field=models.IntegerField(),
    )

    sort_map = {
        'priority':  [priority_order, 'scheduled_for', '-created_at'],
        'scheduled': ['scheduled_for', '-created_at'],
        'newest':    ['-created_at'],
        'oldest':    ['created_at'],
        'property':  ['property__name', priority_order],
    }
    tasks = tasks.order_by(*sort_map.get(sort, sort_map['priority']))

    # ---- Filter pill counts ----
    pill_base = base_qs
    if priority:
        pill_base = pill_base.filter(priority=priority)
    if q:
        pill_base = pill_base.filter(
            Q(description__icontains=q) |
            Q(assigned_to__icontains=q) |
            Q(property__name__icontains=q)
        )
    pill_counts = {
        'all':         pill_base.count(),
        'open':        pill_base.filter(status='open').count(),
        'in_progress': pill_base.filter(status='in_progress').count(),
        'done':        pill_base.filter(status='done').count(),
    }

    # ---- Pagination ----
    paginator = Paginator(tasks, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'bnb/housekeeping_list.html', {
        'tasks': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,

        'status': status,
        'priority': priority,
        'q': q,
        'sort': sort,

        'open_count':         open_count,
        'in_progress_count':  in_progress_count,
        'done_today_count':   done_today_count,
        'overdue_count':      overdue_count,

        'pill_counts': pill_counts,
    })


# ============================================================
#  HOUSEKEEPING — ADD
# ============================================================
@login_required
def housekeeping_add(request):
    org = _org(request)

    if request.method == 'POST':
        form = HousekeepingTaskForm(request.POST)
        form.fields['property'].queryset = Property.objects.filter(organization=org) if org else Property.objects.none()

        if form.is_valid():
            task = form.save(commit=False)
            if task.property and task.property.organization_id == getattr(org, 'id', None):
                if task.status == 'done' and not task.completed_at:
                    task.completed_at = timezone.now()
                task.save()
                
                # NEW: Auto-create Expense if cost > 0
                if task.cost and task.cost > 0:
                    from .models import Expense, ExpenseCategory
                    from .signals import expense_synced
                    
                    # Try to find or create a "Housekeeping" category
                    cat, _ = ExpenseCategory.objects.get_or_create(
                        organization=org, name="Housekeeping",
                        defaults={'description': 'Cleaning and laundry expenses'}
                    )
                    
                    exp = Expense.objects.create(
                        organization=org,
                        property=task.property,
                        category=cat,
                        title=f"Housekeeping: {task.description[:40]}",
                        amount=task.cost,
                        expense_date=task.completed_at.date() if task.completed_at else timezone.localdate(),
                        paid=True
                    )
                    # Manually trigger the signal to update the Ledger
                    expense_synced(sender=Expense, instance=exp, created=True)

                messages.success(request, 'Housekeeping task created.')
                return redirect('bnb_housekeeping')
            else:
                messages.error(request, 'Please choose one of your properties.')
    else:
        form = HousekeepingTaskForm()
        form.fields['property'].queryset = Property.objects.filter(organization=org) if org else Property.objects.none()

    return render(request, 'bnb/housekeeping_form.html', {
        'form': form,
        'mode': 'create',
    })


# ============================================================
#  HOUSEKEEPING — EDIT
# ============================================================
@login_required
def housekeeping_edit(request, task_id):
    org = _org(request)
    task = get_object_or_404(
        HousekeepingTask.objects.select_related('property'),
        id=task_id, property__organization=org,
    )

    if request.method == 'POST':
        form = HousekeepingTaskForm(request.POST, instance=task)
        form.fields['property'].queryset = Property.objects.filter(organization=org) if org else Property.objects.none()

        if form.is_valid():
            updated = form.save(commit=False)
            if updated.status == 'done' and not updated.completed_at:
                updated.completed_at = timezone.now()
            elif updated.status != 'done':
                updated.completed_at = None
            updated.save()

            # NEW: Auto-create Expense if cost > 0 and was just marked done
            if updated.cost and updated.cost > 0:
                from .models import Expense, ExpenseCategory
                from .signals import expense_synced
                
                cat, _ = ExpenseCategory.objects.get_or_create(
                    organization=org, name="Housekeeping",
                    defaults={'description': 'Cleaning and laundry expenses'}
                )
                
                exp = Expense.objects.create(
                    organization=org,
                    property=updated.property,
                    category=cat,
                    title=f"Housekeeping: {updated.description[:40]}",
                    amount=updated.cost,
                    expense_date=updated.completed_at.date() if updated.completed_at else timezone.localdate(),
                    paid=True
                )
                expense_synced(sender=Expense, instance=exp, created=True)

            messages.success(request, 'Task updated.')
            return redirect('bnb_housekeeping')
    else:
        form = HousekeepingTaskForm(instance=task)
        form.fields['property'].queryset = Property.objects.filter(organization=org) if org else Property.objects.none()

    return render(request, 'bnb/housekeeping_form.html', {
        'form': form,
        'mode': 'edit',
        'task': task,
    })


@login_required
def housekeeping_toggle(request, task_id):
    task = get_object_or_404(
        HousekeepingTask, id=task_id, property__organization=_org(request),
    )
    if task.status == 'done':
        task.status = 'open'
        task.completed_at = None
    else:
        task.status = 'done'
        task.completed_at = timezone.now()
    task.save()
    return redirect('bnb_housekeeping')


@login_required
def housekeeping_delete(request, task_id):
    task = get_object_or_404(
        HousekeepingTask, id=task_id, property__organization=_org(request),
    )
    if request.method == 'POST':
        task.delete()
        messages.success(request, 'Task deleted.')
    return redirect('bnb_housekeeping')


# ============================================================
#  MAINTENANCE — LIST
# ============================================================
@login_required
def maintenance_list(request):
    org = _org(request)
    status = request.GET.get('status', '').strip()
    priority = request.GET.get('priority', '').strip()
    q = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'priority').strip()

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    base_qs = (
        MaintenanceRequest.objects
        .filter(property__organization=org)
        .select_related('property')
        if org else MaintenanceRequest.objects.none()
    )

    # ---- Headline counts (from base, before filters) ----
    open_count        = base_qs.filter(status='open').count()
    in_progress_count = base_qs.filter(status='in_progress').count()
    urgent_count      = base_qs.filter(
        status__in=['open', 'in_progress'],
        priority__in=['high', 'urgent'],
    ).count()
    resolved_today = base_qs.filter(
        status='resolved',
        resolved_at__gte=today_start,
    ).count()

    # ---- Apply filters ----
    items = base_qs
    if status:
        items = items.filter(status=status)
    if priority:
        items = items.filter(priority=priority)
    if q:
        items = items.filter(
            Q(issue__icontains=q) |
            Q(description__icontains=q) |
            Q(property__name__icontains=q) |
            Q(reported_by__icontains=q) |
            Q(assigned_to__icontains=q)
        )

    # ---- Sort ----
    priority_order = Case(
        When(priority='urgent', then=0),
        When(priority='high',   then=1),
        When(priority='normal', then=2),
        When(priority='low',    then=3),
        default=4,
        output_field=IntegerField(),
    )

    sort_map = {
        'priority': ['-status', priority_order, '-created_at'],
        'newest':   ['-created_at'],
        'oldest':   ['created_at'],
        'property': ['property__name', priority_order],
    }
    items = items.order_by(*sort_map.get(sort, sort_map['priority']))

    # ---- Filter pill counts (respect search & priority, but not status) ----
    pill_base = base_qs
    if priority:
        pill_base = pill_base.filter(priority=priority)
    if q:
        pill_base = pill_base.filter(
            Q(issue__icontains=q) |
            Q(description__icontains=q) |
            Q(property__name__icontains=q) |
            Q(reported_by__icontains=q) |
            Q(assigned_to__icontains=q)
        )
    pill_counts = {
        'all':         pill_base.count(),
        'open':        pill_base.filter(status='open').count(),
        'in_progress': pill_base.filter(status='in_progress').count(),
        'resolved':    pill_base.filter(status='resolved').count(),
    }

    # ---- Pagination ----
    paginator = Paginator(items, 24)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'bnb/maintenance_list.html', {
        'items': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,

        'status': status,
        'priority': priority,
        'q': q,
        'sort': sort,

        'open_count':        open_count,
        'in_progress_count': in_progress_count,
        'urgent_count':      urgent_count,
        'resolved_today':    resolved_today,

        'pill_counts': pill_counts,
    })
    

# ---------------------------------------------------------------------------
#  MAINTENANCE — ADD
# ---------------------------------------------------------------------------
@login_required
def maintenance_add(request):
    org = _org(request)

    if request.method == 'POST':
        form = MaintenanceRequestForm(request.POST)
        # Scope the property dropdown to this org only
        form.fields['property'].queryset = (
            Property.objects.filter(organization=org) if org
            else Property.objects.none()
        )

        if form.is_valid():
            item = form.save(commit=False)
            # Safety net: the form already validated property is in the
            # org-scoped queryset, but assert it again.
            if org and item.property.organization_id != org.id:
                messages.error(request, 'That property does not belong to your organization.')
                return redirect('bnb_maintenance_add')

            # If created already resolved, stamp resolved_at
            if item.status == 'resolved' and not item.resolved_at:
                item.resolved_at = timezone.now()

            item.save()
            messages.success(request, 'Maintenance request created.')
            return redirect('bnb_maintenance')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = MaintenanceRequestForm()
        form.fields['property'].queryset = (
            Property.objects.filter(organization=org) if org
            else Property.objects.none()
        )

    return render(request, 'bnb/maintenance_form.html', {
        'form': form,
        'properties': Property.objects.filter(organization=org) if org else Property.objects.none(),
    })


# ---------------------------------------------------------------------------
#  MAINTENANCE — EDIT
# ---------------------------------------------------------------------------
@login_required
def maintenance_edit(request, request_id):
    org = _org(request)
    item = get_object_or_404(
        MaintenanceRequest, id=request_id, property__organization=org,
    )

    if request.method == 'POST':
        form = MaintenanceRequestForm(request.POST, instance=item)
        form.fields['property'].queryset = (
            Property.objects.filter(organization=org) if org
            else Property.objects.none()
        )

        if form.is_valid():
            obj = form.save(commit=False)

            # Re-assert property org ownership
            if org and obj.property.organization_id != org.id:
                messages.error(request, 'That property does not belong to your organization.')
                return redirect('bnb_maintenance_edit', request_id=item.id)

            # Keep resolved_at in sync with status transitions
            previous_status = MaintenanceRequest.objects \
                .filter(pk=item.pk) \
                .values_list('status', flat=True) \
                .first()

            if obj.status == 'resolved' and previous_status != 'resolved':
                obj.resolved_at = timezone.now()
            elif obj.status != 'resolved':
                obj.resolved_at = None

            obj.save()
            messages.success(request, 'Maintenance request updated.')
            return redirect('bnb_maintenance')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = MaintenanceRequestForm(instance=item)
        form.fields['property'].queryset = (
            Property.objects.filter(organization=org) if org
            else Property.objects.none()
        )

    return render(request, 'bnb/maintenance_form.html', {
        'form': form,
        'item': item,
        'properties': Property.objects.filter(organization=org) if org else Property.objects.none(),
    })


@login_required
def maintenance_delete(request, request_id):
    item = get_object_or_404(
        MaintenanceRequest, id=request_id, property__organization=_org(request),
    )
    if request.method == 'POST':
        item.delete()
        messages.success(request, 'Maintenance request deleted.')
    return redirect('bnb_maintenance')




# ============================================================
#  EXPENSES — LIST
# ============================================================
@login_required
def expense_list(request):
    org = _org(request)
    today = timezone.now().date()
    month_start = today.replace(day=1)

    # ---------- Filters from querystring ----------
    frequency = request.GET.get('frequency', '') or ''
    paid_filter = request.GET.get('paid', '') or ''
    category_id = request.GET.get('category', '') or ''
    q = (request.GET.get('q', '') or '').strip()
    sort = request.GET.get('sort', 'newest') or 'newest'

    base_qs = (
        Expense.objects
        .filter(organization=org)
        .select_related('property', 'category')
        if org else Expense.objects.none()
    )

    # ---------- Headline totals (over ALL expenses, unfiltered) ----------
    totals_qs = base_qs
    total_all = totals_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_month = (
        totals_qs.filter(expense_date__gte=month_start)
        .aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')
    total_unpaid = (
        totals_qs.filter(paid=False)
        .aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')
    count_all = totals_qs.count()

    # ---------- Pill counts (unfiltered by that specific pill) ----------
    pill_counts = {
        'all':      count_all,
        'one_off':  totals_qs.filter(frequency='one_off').count(),
        'daily':    totals_qs.filter(frequency='daily').count(),
        'weekly':   totals_qs.filter(frequency='weekly').count(),
        'monthly':  totals_qs.filter(frequency='monthly').count(),
        'quarterly':totals_qs.filter(frequency='quarterly').count(),
        'yearly':   totals_qs.filter(frequency='yearly').count(),
    }

    # ---------- Apply filters ----------
    qs = base_qs
    if frequency:
        qs = qs.filter(frequency=frequency)
    if paid_filter == 'paid':
        qs = qs.filter(paid=True)
    elif paid_filter == 'unpaid':
        qs = qs.filter(paid=False)
    if category_id:
        try:
            qs = qs.filter(category_id=int(category_id))
        except (ValueError, TypeError):
            pass
    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(vendor__icontains=q) |
            Q(property__name__icontains=q) |
            Q(category__name__icontains=q)
        )

    # ---------- Sort ----------
    sort_map = {
        'newest':  ('-expense_date', '-created_at'),
        'oldest':  ('expense_date', 'created_at'),
        'amount':  ('-amount', '-expense_date'),
        'amount_asc': ('amount', '-expense_date'),
        'title':   ('title',),
    }
    qs = qs.order_by(*sort_map.get(sort, sort_map['newest']))

    # ---------- Totals for the FILTERED set ----------
    filtered_total = qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    filtered_count = qs.count()

    # ---------- Category breakdown for filter dropdown + top categories ----------
    categories = (
        ExpenseCategory.objects.filter(organization=org).order_by('name')
        if org else ExpenseCategory.objects.none()
    )

    by_category = (
        totals_qs
        .values('category__name')
        .annotate(total=Sum('amount'), count=Count('id'))
        .order_by('-total')[:6]
    )
    total_by_cat = sum(
        (row['total'] or Decimal('0.00')) for row in by_category
    ) or Decimal('0.00')
    for row in by_category:
        row['pct'] = (
            round(float(row['total']) / float(total_by_cat) * 100, 1)
            if total_by_cat else 0
        )

    # ---------- VAT status (for the info strip in the template) ----------
    # NEW: tell the template whether VAT is enabled so it can render
    # the appropriate hint under the KPI cards. Doesn't affect any logic.
    from .models import get_financial_settings
    settings = get_financial_settings(org) if org else None
    vat_enabled = bool(settings and settings.vat_enabled)
    vat_label = settings.vat_label if settings else 'VAT'

    context = {
        'expenses': qs,
        'filtered_total': filtered_total,
        'filtered_count': filtered_count,
        'frequency': frequency,
        'paid_filter': paid_filter,
        'category_id': category_id,
        'q': q,
        'sort': sort,
        'categories': categories,
        'pill_counts': pill_counts,
        'total_all': total_all,
        'total_month': total_month,
        'total_unpaid': total_unpaid,
        'by_category': by_category,
        'total_by_cat': total_by_cat,

        # NEW
        'vat_enabled': vat_enabled,
        'vat_label': vat_label,
    }
    return render(request, 'bnb/expense_list.html', context)


# ============================================================
#  EXPENSES — ADD
# ============================================================
@login_required
def expense_add(request):
    org = _org(request)

    def _scoped(form):
        form.fields['property'].queryset = (
            Property.objects.filter(organization=org).order_by('name')
            if org else Property.objects.none()
        )
        form.fields['category'].queryset = (
            ExpenseCategory.objects.filter(organization=org).order_by('name')
            if org else ExpenseCategory.objects.none()
        )
        return form

    if request.method == 'POST':
        form = _scoped(ExpenseForm(request.POST, request.FILES))

        if form.is_valid():
            e = form.save(commit=False)
            e.organization = org
            e.created_by = request.user
            # Belt-and-braces property ownership
            if org and e.property_id and e.property.organization_id != org.id:
                form.add_error('property', 'That property does not belong to your organization.')
            else:
                e.save()
                # The post_save signal creates the LedgerEntry automatically.
                # No manual mirror call needed.
                messages.success(request, 'Expense added.')
                return redirect('bnb_expense_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = _scoped(ExpenseForm())

    return render(request, 'bnb/expense_form.html', {
        'form': form,
        'properties': Property.objects.filter(organization=org) if org else Property.objects.none(),
        'categories': ExpenseCategory.objects.filter(organization=org) if org else ExpenseCategory.objects.none(),
    })


# ============================================================
#  EXPENSES — EDIT
# ============================================================
@login_required
def expense_edit(request, expense_id):
    org = _org(request)
    expense = get_object_or_404(Expense, id=expense_id, organization=org)

    def _scoped(form):
        form.fields['property'].queryset = (
            Property.objects.filter(organization=org).order_by('name')
            if org else Property.objects.none()
        )
        form.fields['category'].queryset = (
            ExpenseCategory.objects.filter(organization=org).order_by('name')
            if org else ExpenseCategory.objects.none()
        )
        return form

    if request.method == 'POST':
        form = _scoped(ExpenseForm(request.POST, request.FILES, instance=expense))

        if form.is_valid():
            obj = form.save(commit=False)
            if org and obj.property_id and obj.property.organization_id != org.id:
                form.add_error('property', 'That property does not belong to your organization.')
            else:
                obj.save()
                # The post_save signal updates the LedgerEntry in place.
                messages.success(request, 'Expense updated.')
                return redirect('bnb_expense_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = _scoped(ExpenseForm(instance=expense))

    return render(request, 'bnb/expense_form.html', {
        'form': form,
        'expense': expense,
        'properties': Property.objects.filter(organization=org) if org else Property.objects.none(),
        'categories': ExpenseCategory.objects.filter(organization=org) if org else ExpenseCategory.objects.none(),
    })


# ============================================================
#  EXPENSES — DELETE
# ============================================================
@login_required
def expense_delete(request, expense_id):
    expense = get_object_or_404(
        Expense, id=expense_id, organization=_org(request),
    )
    if request.method == 'POST':
        # The post_delete signal on Expense removes the LedgerEntry mirror.
        expense.delete()
        messages.success(request, 'Expense deleted.')
    return redirect('bnb_expense_list')




# ============================================================
#  REVENUE — LIST (Driven by Ledger / Bookings)
# ============================================================
@login_required
def revenue_list(request):
    from .models import LedgerEntry
    
    org = _org(request)
    today = timezone.localdate()
    month_start = today.replace(day=1)

    # ---------- Filters from querystring ----------
    q = (request.GET.get('q', '') or '').strip()
    sort = (request.GET.get('sort', 'newest') or 'newest')

    # We only want actual booking revenue, not manual extra revenue
    base_qs = (
        LedgerEntry.objects
        .filter(organization=org, kind='revenue', source='booking')
        .select_related('property', 'booking')
        if org else LedgerEntry.objects.none()
    )

    # ---------- Headline totals ----------
    total_all = base_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_month = (
        base_qs.filter(occurred_at__date__gte=month_start)
        .aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')
    count_all = base_qs.count()

    # ---------- Apply search ----------
    qs = base_qs
    if q:
        qs = qs.filter(
            Q(reason__icontains=q) |
            Q(property__name__icontains=q) |
            Q(booking__guest_name__icontains=q)
        )

    # ---------- Sort ----------
    sort_map = {
        'newest':     ('-occurred_at',),
        'oldest':     ('occurred_at',),
        'amount':     ('-amount', '-occurred_at'),
        'amount_asc': ('amount', '-occurred_at'),
        'title':      ('reason',),
    }
    qs = qs.order_by(*sort_map.get(sort, sort_map['newest']))

    # ---------- Filtered totals ----------
    filtered_total = qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    filtered_count = qs.count()

    # ---------- Breakdown by Property (instead of Source) ----------
    by_property = (
        base_qs
        .values('property__name')
        .annotate(total=Sum('amount'), count=Count('id'))
        .order_by('-total')[:6]
    )
    total_by_prop = sum(
        (row['total'] or Decimal('0.00')) for row in by_property
    ) or Decimal('0.00')
    
    for row in by_property:
        row['label'] = row['property__name'] or 'Unassigned'
        row['pct'] = (
            round(float(row['total']) / float(total_by_prop) * 100, 1)
            if total_by_prop else 0
        )

    return render(request, 'bnb/revenue_list.html', {
        'revenues': qs,
        'filtered_total': filtered_total,
        'filtered_count': filtered_count,
        'q': q,
        'sort': sort,
        'total_all': total_all,
        'total_month': total_month,
        'by_property': by_property,
        'total_by_prop': total_by_prop,
    })


# ============================================================
#  REVENUE — ADD (Disabled for manual entry)
# ============================================================
@login_required
def revenue_add(request):
    """
    Revenue is strictly driven by Bookings. Manual entry is disabled
    to prevent double-counting. Users are redirected to the ledger.
    """
    messages.info(
        request, 
        "Revenue is automatically recorded when a booking is confirmed. "
        "To record non-booking income (like minibar or late checkouts), "
        "please log it as an 'Extra Revenue' in the General Ledger."
    )
    return redirect('bnb_finance_ledger')





# bnb/views.py

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.shortcuts import render
from django.utils import timezone

from .models import Booking, Expense, Revenue, REVENUE_STATUSES


FINANCE_WINDOWS = {
    'today': {'label': 'Today',          'days': 0,    'bucket': 'day'},
    '7':     {'label': 'Last 7 days',    'days': 7,    'bucket': 'day'},
    '30':    {'label': 'Last 30 days',   'days': 30,   'bucket': 'day'},
    '90':    {'label': 'Last 90 days',   'days': 90,   'bucket': 'week'},
    '180':   {'label': 'Last 6 months',  'days': 180,  'bucket': 'week'},
    '365':   {'label': 'Last 12 months', 'days': 365,  'bucket': 'month'},
    'all':   {'label': 'All time',       'days': None, 'bucket': 'month'},
}


@login_required
def finance_dashboard(request):
    """
    Window-based finance dashboard driven by LedgerEntry.
    """
    import math
    from datetime import datetime, timedelta
    from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
    from .models import LedgerEntry

    org = _org(request)
    today = timezone.localdate()
    current_tz = timezone.get_current_timezone()

    # ------------------------------------------------------------------
    #  Resolve the selected window
    # ------------------------------------------------------------------
    window_key = request.GET.get('window', '30')
    if window_key not in FINANCE_WINDOWS:
        window_key = '30'
    window = FINANCE_WINDOWS[window_key]
    days = window['days']
    bucket = window['bucket']

    def _window_bounds(days):
        """Return (start_dt, end_dt) for the given day window (half-open)."""
        def dt(d, end=False):
            if end:
                next_day = d + timedelta(days=1)
                return timezone.make_aware(
                    datetime.combine(next_day, datetime.min.time()),
                    timezone=current_tz,
                )
            return timezone.make_aware(
                datetime.combine(d, datetime.min.time()),
                timezone=current_tz,
            )

        if days is None:
            return None, None
        if days == 0:
            return dt(today), dt(today, end=True)
        start = today - timedelta(days=days - 1)
        return dt(start), dt(today, end=True)

    start_dt, end_dt = _window_bounds(days)

    # ------------------------------------------------------------------
    #  Base ledger queryset
    # ------------------------------------------------------------------
    entries = (
        LedgerEntry.objects.filter(organization=org)
        if org else LedgerEntry.objects.none()
    )
    if start_dt:
        entries = entries.filter(occurred_at__gte=start_dt)
    if end_dt:
        entries = entries.filter(occurred_at__lt=end_dt)   # EXCLUSIVE

    # ------------------------------------------------------------------
    #  Headline totals
    # ------------------------------------------------------------------
    window_revenue = (
        entries.filter(kind='revenue').aggregate(t=Sum('amount'))['t']
        or Decimal('0.00')
    )
    window_refunds = (
        entries.filter(kind='refund').aggregate(t=Sum('amount'))['t']
        or Decimal('0.00')
    )
    window_expenses = (
        entries.filter(kind='expense').aggregate(t=Sum('amount'))['t']
        or Decimal('0.00')
    )

    net_revenue = window_revenue - window_refunds
    window_profit = net_revenue - window_expenses
    window_margin = (
        round(float(window_profit) / float(net_revenue) * 100, 1)
        if net_revenue else 0
    )

    # ------------------------------------------------------------------
    #  Time-series chart
    # ------------------------------------------------------------------
    if bucket == 'day':
        trunc = TruncDate('occurred_at', tzinfo=current_tz)
    elif bucket == 'week':
        trunc = TruncWeek('occurred_at', tzinfo=current_tz)
    else:
        trunc = TruncMonth('occurred_at', tzinfo=current_tz)

    rev_series = list(
        entries.filter(kind='revenue')
        .annotate(bucket=trunc).values('bucket')
        .annotate(total=Sum('amount')).order_by('bucket')
    )
    exp_series = list(
        entries.filter(kind='expense')
        .annotate(bucket=trunc).values('bucket')
        .annotate(total=Sum('amount')).order_by('bucket')
    )

    buckets = {}

    def _key(d):
        return d.replace(day=1) if bucket == 'month' else d

    for row in rev_series:
        if not row['bucket']:
            continue
        k = _key(row['bucket'])
        buckets.setdefault(k, {'revenue': 0.0, 'expenses': 0.0})
        buckets[k]['revenue'] = float(row['total'] or 0)

    for row in exp_series:
        if not row['bucket']:
            continue
        k = _key(row['bucket'])
        buckets.setdefault(k, {'revenue': 0.0, 'expenses': 0.0})
        buckets[k]['expenses'] = float(row['total'] or 0)

    ordered = sorted(buckets.items())

    def _label(d):
        if bucket in ('day', 'week'):
            return d.strftime('%d %b')
        return d.strftime('%b %y')

    chart_data = [
        {'label': _label(k), 'revenue': v['revenue'], 'expenses': v['expenses']}
        for k, v in ordered
    ]

    chart_max = max(
        (max(p['revenue'], p['expenses']) for p in chart_data), default=0,
    ) or 1

    # ------------------------------------------------------------------
    #  Donut: expense breakdown by reason
    # ------------------------------------------------------------------
    raw_cats = list(
        entries.filter(kind='expense')
        .values('reason')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    total_cat = sum(
        (c['total'] or Decimal('0.00')) for c in raw_cats
    ) or Decimal('0.00')

    palette = [
        '#0ea5e9', '#f59e0b', '#10b981', '#8b5cf6',
        '#ef4444', '#06b6d4', '#eab308', '#f97316',
        '#ec4899', '#14b8a6',
    ]

    donut_slices = []
    cumulative = 0.0
    for i, c in enumerate(raw_cats[:8]):
        amt = float(c['total'] or 0)
        if not amt:
            continue
        pct = (amt / float(total_cat) * 100) if total_cat else 0
        label = (c['reason'] or 'Uncategorised')
        if len(label) > 28:
            label = label[:25] + '…'
        donut_slices.append({
            'label': label,
            'amount': amt,
            'pct': round(pct, 1),
            'color': palette[i % len(palette)],
            'offset': round(cumulative, 3),
        })
        cumulative += pct

    # ------------------------------------------------------------------
    #  Period comparison bars — with square-root scaling
    # ------------------------------------------------------------------
    period_defs = [
        ('Today',   0),
        ('7 days',  7),
        ('30 days', 30),
        ('90 days', 90),
        ('1 year',  365),
    ]
    base_entries = (
        LedgerEntry.objects.filter(organization=org)
        if org else LedgerEntry.objects.none()
    )
    period_rows = []
    for label, back in period_defs:
        s, e = _window_bounds(back)
        qs = base_entries
        if s:
            qs = qs.filter(occurred_at__gte=s)
        if e:
            qs = qs.filter(occurred_at__lt=e)
            
        rev = (
            qs.filter(kind='revenue').aggregate(t=Sum('amount'))['t']
            or Decimal('0')
        )
        exp = (
            qs.filter(kind='expense').aggregate(t=Sum('amount'))['t']
            or Decimal('0')
        )
        period_rows.append({
            'label': label,
            'revenue': float(rev),
            'expenses': float(exp),
            'profit': float(rev - exp),
        })

    # Find the absolute maximum to scale against
    max_period = max(
        (max(r['revenue'], r['expenses']) for r in period_rows),
        default=0,
    ) or 1

    for row in period_rows:
        # Calculate true percentages (for labels)
        row['rev_pct'] = round(row['revenue'] / max_period * 100, 1)
        row['exp_pct'] = round(row['expenses'] / max_period * 100, 1)
        
        # Calculate visual heights using math.sqrt() so small numbers 
        # don't get crushed to 0% height next to massive numbers.
        if row['revenue'] > 0:
            row['rev_height'] = max(2, round(math.sqrt(row['revenue'] / max_period) * 100, 1))
        else:
            row['rev_height'] = 0
            
        if row['expenses'] > 0:
            row['exp_height'] = max(2, round(math.sqrt(row['expenses'] / max_period) * 100, 1))
        else:
            row['exp_height'] = 0

    # ------------------------------------------------------------------
    #  Recent activity feed — from the ledger
    # ------------------------------------------------------------------
    recent_revenues = list(
        entries.filter(kind='revenue')
        .order_by('-occurred_at')[:6]
    )
    recent_expenses = list(
        entries.filter(kind='expense')
        .order_by('-occurred_at')[:6]
    )

    # ------------------------------------------------------------------
    #  Context
    # ------------------------------------------------------------------
    context = {
        'window_key': window_key,
        'window_label': window['label'],
        'available_windows': [
            {'key': k, 'label': v['label']}
            for k, v in FINANCE_WINDOWS.items()
        ],

        # KPIs
        'window_revenue': window_revenue,
        'window_refunds': window_refunds,
        'window_expenses': window_expenses,
        'window_profit': window_profit,
        'window_margin': window_margin,
        'window_bucket': bucket,

        # Chart
        'chart_data': chart_data,
        'chart_max': chart_max,
        'has_chart_data': len(chart_data) > 0,

        # Donut
        'donut_slices': donut_slices,
        'total_cat': total_cat,
        'has_donut': bool(donut_slices),

        # Period comparison
        'period_rows': period_rows,

        # Activity
        'recent_revenues': recent_revenues,
        'recent_expenses': recent_expenses,

        # Legacy safety keys
        'total_revenue': window_revenue,
        'total_expenses': window_expenses,
        'total_profit': window_profit,
        'profit_margin': window_margin,
        'by_category': donut_slices,
    }
    return render(request, 'bnb/finance_dashboard.html', context)


def _month_start(d):
    """First day of the month containing d."""
    return d.replace(day=1)


def _next_month_start(d):
    """First day of the month after d."""
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


@login_required
def finance_profit_margin(request):
    """
    Profit margin report driven by LedgerEntry.
    Uses string-based month matching to avoid timezone mismatch bugs.
    """
    from collections import defaultdict
    from decimal import Decimal
    from .models import LedgerEntry
    import json

    org = _org(request)
    if org is None:
        messages.error(request, 'No organization linked.')
        return redirect('dashboard')

    today = timezone.localdate()
    
    # 1. Build the 12 month strings (e.g., "2025-11", "2025-12", ... "2026-10")
    month_keys = []
    cur = today.replace(day=1)
    for _ in range(12):
        month_keys.append(cur.strftime('%Y-%m'))
        if cur.month == 1:
            cur = cur.replace(year=cur.year - 1, month=12, day=1)
        else:
            cur = cur.replace(month=cur.month - 1, day=1)
    month_keys.reverse()

    # 2. Fetch all entries
    entries = LedgerEntry.objects.filter(
        organization=org, 
        kind__in=['revenue', 'expense', 'refund']
    )

    # 3. Group by string key
    months_dict = defaultdict(lambda: {'revenue': Decimal('0.00'), 'expense': Decimal('0.00'), 'refund': Decimal('0.00')})
    
    for entry in entries:
        local_dt = timezone.localtime(entry.occurred_at)
        key = local_dt.strftime('%Y-%m')  # e.g., "2026-10"
        
        if entry.kind == 'revenue':
            months_dict[key]['revenue'] += entry.amount
        elif entry.kind == 'expense':
            months_dict[key]['expense'] += entry.amount
        elif entry.kind == 'refund':
            months_dict[key]['refund'] += entry.amount

    # 4. Build the monthly_data array
    monthly_data = []
    total_revenue = Decimal('0.00')
    total_expenses = Decimal('0.00')
    total_profit = Decimal('0.00')

    prev_revenue = None
    prev_expenses = None
    prev_profit = None
    prev_margin = None
    
    # For Chart.js
    chart_labels = []
    chart_revenue = []
    chart_expenses = []

    for key in month_keys:
        m = months_dict[key]
        
        net_rev = m['revenue'] - m['refund']
        exp = m['expense']
        profit = net_rev - exp
        margin = round(((profit / net_rev * 100) if net_rev else 0), 1)

        rev_delta = None
        exp_delta = None
        profit_delta = None
        margin_delta = None
        
        if prev_revenue is not None:
            if prev_revenue > 0:
                rev_delta = round((float(net_rev - prev_revenue) / float(prev_revenue)) * 100, 1)
            if prev_expenses > 0:
                exp_delta = round((float(exp - prev_expenses) / float(prev_expenses)) * 100, 1)
            if prev_profit != 0:
                profit_delta = round((float(profit - prev_profit) / abs(float(prev_profit))) * 100, 1)
            margin_delta = round(float(margin - (prev_margin or 0)), 1)

        from datetime import datetime
        dt_obj = datetime.strptime(key, '%Y-%m').date()

        monthly_data.append({
            'month': dt_obj,
            'month_str': dt_obj.strftime('%b %y'),
            'revenue': net_rev,
            'expenses': exp,
            'profit': profit,
            'margin': margin,
            'rev_delta': rev_delta,
            'exp_delta': exp_delta,
            'profit_delta': profit_delta,
            'margin_delta': margin_delta,
            'positive': profit >= 0,
        })
        
        chart_labels.append(dt_obj.strftime('%b %y'))
        chart_revenue.append(float(net_rev))
        chart_expenses.append(float(exp))

        total_revenue += net_rev
        total_expenses += exp
        total_profit += profit

        prev_revenue = net_rev
        prev_expenses = exp
        prev_profit = profit
        prev_margin = margin

    # 5. Calculate Bar scaling
    max_profit = max((abs(float(r['profit'])) for r in monthly_data), default=0) or 1.0
    max_rev_or_exp = max(
        (max(float(r['revenue']), float(r['expenses'])) for r in monthly_data),
        default=0,
    ) or 1.0

    for r in monthly_data:
        r['profit_pct'] = max(2, round(abs(float(r['profit'])) / max_profit * 100, 1)) if r['profit'] != 0 else 0
        r['rev_pct'] = max(2, round(float(r['revenue']) / max_rev_or_exp * 100, 1)) if r['revenue'] > 0 else 0
        r['exp_pct'] = max(2, round(float(r['expenses']) / max_rev_or_exp * 100, 1)) if r['expenses'] > 0 else 0

    overall_margin = (
        round(float(total_profit) / float(total_revenue) * 100, 1)
        if total_revenue else 0
    )

    best_month = max(monthly_data, key=lambda r: float(r['profit']), default=None)
    worst_month = min(monthly_data, key=lambda r: float(r['profit']), default=None)
    avg_profit = total_profit / Decimal('12') if monthly_data else Decimal('0.00')

    return render(request, 'bnb/finance_profit_margin.html', {
        'monthly_data': monthly_data,
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'total_profit': total_profit,
        'overall_margin': overall_margin,
        'avg_profit': avg_profit,
        'best_month': best_month,
        'worst_month': worst_month,
        'pm_max_profit': max_profit,
        
        # Chart Data
        'chart_labels': json.dumps(chart_labels),
        'chart_revenue': json.dumps(chart_revenue),
        'chart_expenses': json.dumps(chart_expenses),
    })
    
    

@login_required
def finance_expenses_by_period(request, period):
    org = _org(request)
    today = timezone.now().date()

    mapping = {
        'daily':     today,
        'weekly':    today - timedelta(days=7),
        'monthly':   today - timedelta(days=30),
        'quarterly': today - timedelta(days=90),
        'yearly':    today - timedelta(days=365),
    }
    start = mapping.get(period, today - timedelta(days=30))

    expenses = Expense.objects.filter(
        organization=org, expense_date__gte=start,
    ).select_related('property', 'category').order_by('-expense_date')

    total = expenses.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    return render(request, 'bnb/finance_expenses_by_period.html', {
        'expenses': expenses,
        'total': total,
        'period': period,
        'start': start,
    })



# ============================================================
#  INVOICES — LIST
# ============================================================
@login_required
def invoice_list(request):
    from .models import INVOICE_OPEN_STATUSES
    org = _org(request)
    today = timezone.localdate()

    # ---------- Filters ----------
    status_filter = request.GET.get('status', '') or ''
    q = (request.GET.get('q', '') or '').strip()
    sort = request.GET.get('sort', 'newest') or 'newest'

    base_qs = (
        Invoice.objects
        .filter(organization=org)
        .select_related('booking', 'booking__property')
        if org else Invoice.objects.none()
    )

    # ---------- Headline totals ----------
    total_invoiced = base_qs.aggregate(t=Sum('total'))['t'] or Decimal('0.00')
    total_paid_all = base_qs.aggregate(t=Sum('amount_paid'))['t'] or Decimal('0.00')

    open_invoices = base_qs.filter(status__in=INVOICE_OPEN_STATUSES)
    total_outstanding = sum(
        (inv.balance for inv in open_invoices if inv.balance > 0),
        Decimal('0.00'),
    )

    # Overdue logic
    overdue_qs = open_invoices.filter(due_date__lt=today)
    overdue_count = overdue_qs.count()

    # ---------- Status counts ----------
    pill_counts = {
        'all':     base_qs.count(),
        'draft':   base_qs.filter(status='draft').count(),
        'sent':    base_qs.filter(status='sent').count(),
        'paid':    base_qs.filter(status='paid').count(),
        'overdue': overdue_count,
        'void':    base_qs.filter(status='void').count(),
    }

    # ---------- Apply filters ----------
    qs = base_qs
    if status_filter == 'overdue':
        qs = qs.filter(status__in=INVOICE_OPEN_STATUSES, due_date__lt=today)
    elif status_filter:
        qs = qs.filter(status=status_filter)
    if q:
        qs = qs.filter(
            Q(invoice_number__icontains=q) |
            Q(guest_name__icontains=q) |
            Q(guest_email__icontains=q) |
            Q(booking__guest_name__icontains=q)
        )

    # ---------- Sort ----------
    sort_map = {
        'newest':    ('-issue_date', '-created_at'),
        'oldest':    ('issue_date', 'created_at'),
        'total':     ('-total', '-issue_date'),
        'balance':   ('-total', '-issue_date'),
        'due_soon':  ('due_date',),
    }
    qs = qs.order_by(*sort_map.get(sort, sort_map['newest']))

    if sort == 'balance':
        qs = sorted(qs, key=lambda i: i.balance, reverse=True)

    filtered_count = len(qs) if isinstance(qs, list) else qs.count()
    filtered_total = sum(
        (inv.total for inv in qs), Decimal('0.00'),
    )

    return render(request, 'bnb/invoice_list.html', {
        'invoices': qs,
        'filtered_count': filtered_count,
        'filtered_total': filtered_total,
        'status_filter': status_filter,
        'q': q,
        'sort': sort,
        'pill_counts': pill_counts,
        'total_invoiced': total_invoiced,
        'total_paid_all': total_paid_all,
        'total_outstanding': total_outstanding,
        'overdue_count': overdue_count,
    })


# ============================================================
#  INVOICES — ADD (Starts from a Booking)
# ============================================================
@login_required
def invoice_add(request):
    org = _org(request)
    
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        # Scope to org bookings
        form.fields['booking'].queryset = Booking.objects.filter(property__organization=org).order_by('-created_at')
        
        if form.is_valid():
            inv = form.save(commit=False)
            inv.organization = org
            if not inv.invoice_number:
                inv.invoice_number = f"INV-{timezone.now().strftime('%Y%m%d%H%M%S')}"
            
            # Auto-fill guest details from the booking if left blank
            if inv.booking:
                if not inv.guest_name:
                    inv.guest_name = inv.booking.guest_name
                if not inv.guest_email:
                    inv.guest_email = inv.booking.guest_email
                if not inv.total:
                    inv.total = inv.booking.total_amount
            
            inv.save()
            messages.success(request, 'Invoice created.')
            return redirect('bnb_invoice_detail', invoice_id=inv.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Pre-select booking if passed in URL (e.g. from booking detail page)
        initial = {}
        booking_id = request.GET.get('booking')
        if booking_id:
            try:
                b = Booking.objects.get(id=booking_id, property__organization=org)
                initial = {
                    'booking': b.id,
                    'guest_name': b.guest_name,
                    'guest_email': b.guest_email,
                    'total': b.total_amount,
                    'subtotal': b.total_amount, # Assuming no tax initially
                }
            except Booking.DoesNotExist:
                pass
                
        form = InvoiceForm(initial=initial)
        form.fields['booking'].queryset = Booking.objects.filter(property__organization=org).order_by('-created_at')

    return render(request, 'bnb/invoice_form.html', {
        'form': form,
    })


# ============================================================
#  INVOICES — DETAIL
# ============================================================
@login_required
def invoice_detail(request, invoice_id):
    inv = get_object_or_404(
        Invoice.objects.select_related('booking', 'booking__property'),
        id=invoice_id, organization=_org(request),
    )
    payments = inv.payments.order_by('-payment_date')
    total_paid_via_payments = payments.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    return render(request, 'bnb/invoice_detail.html', {
        'invoice': inv,
        'payments': payments,
        'total_paid_via_payments': total_paid_via_payments,
    })


# ============================================================
#  INVOICES — PRINT (A4 Layout)
# ============================================================
@login_required
def invoice_print(request, invoice_id):
    inv = get_object_or_404(
        Invoice.objects.select_related('booking', 'booking__property__organization'),
        id=invoice_id, organization=_org(request),
    )
    return render(request, 'bnb/invoice_print.html', {'invoice': inv})




# ============================================================
#  PAYMENTS — LIST
# ============================================================
@login_required
def payment_list(request):
    org = _org(request)
    today = timezone.localdate()
    month_start = today.replace(day=1)

    # ---------- Filters ----------
    method_filter = request.GET.get('method', '') or ''
    q = (request.GET.get('q', '') or '').strip()
    sort = (request.GET.get('sort', 'newest') or 'newest')

    base_qs = (
        Payment.objects
        .filter(organization=org)
        .select_related('booking', 'invoice')
        if org else Payment.objects.none()
    )

    # ---------- Headline totals ----------
    total_all = base_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_month = (
        base_qs.filter(payment_date__gte=month_start)
        .aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')
    count_all = base_qs.count()

    # ---------- Pill counts per method ----------
    pill_counts = {'all': count_all}
    for key, _label in Payment.METHOD:
        pill_counts[key] = base_qs.filter(method=key).count()

    # ---------- Apply filters ----------
    qs = base_qs
    if method_filter:
        qs = qs.filter(method=method_filter)
    if q:
        qs = qs.filter(
            Q(reference__icontains=q) |
            Q(notes__icontains=q) |
            Q(booking__guest_name__icontains=q) |
            Q(invoice__invoice_number__icontains=q) |
            Q(invoice__guest_name__icontains=q)
        )

    # ---------- Sort ----------
    sort_map = {
        'newest':     ('-payment_date', '-created_at'),
        'oldest':     ('payment_date', 'created_at'),
        'amount':     ('-amount', '-payment_date'),
        'amount_asc': ('amount', '-payment_date'),
    }
    qs = qs.order_by(*sort_map.get(sort, sort_map['newest']))

    # ---------- Filtered totals ----------
    filtered_total = qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    filtered_count = qs.count()

    # ---------- Breakdown by method ----------
    by_method = (
        base_qs
        .values('method')
        .annotate(total=Sum('amount'), count=Count('id'))
        .order_by('-total')
    )
    method_labels = dict(Payment.METHOD)
    total_by_method = sum(
        (row['total'] or Decimal('0.00')) for row in by_method
    ) or Decimal('0.00')
    for row in by_method:
        row['label'] = method_labels.get(row['method'], row['method'])
        row['pct'] = (
            round(float(row['total']) / float(total_by_method) * 100, 1)
            if total_by_method else 0
        )

    return render(request, 'bnb/payment_list.html', {
        'payments': qs,
        'filtered_total': filtered_total,
        'filtered_count': filtered_count,
        'method_filter': method_filter,
        'q': q,
        'sort': sort,
        'pill_counts': pill_counts,
        'total_all': total_all,
        'total_month': total_month,
        'by_method': by_method,
        'total_by_method': total_by_method,
        'method_choices': Payment.METHOD,
    })


# ============================================================
#  PAYMENTS — ADD
# ============================================================
@login_required
def payment_add(request):
    org = _org(request)

    def _scoped(form):
        form.fields['booking'].queryset = (
            Booking.objects
            .filter(property__organization=org)
            .select_related('property')
            .order_by('-created_at')
            if org else Booking.objects.none()
        )
        form.fields['invoice'].queryset = (
            Invoice.objects
            .filter(organization=org)
            .order_by('-issue_date')
            if org else Invoice.objects.none()
        )
        form.fields['booking'].required = False
        form.fields['invoice'].required = False
        form.fields['booking'].empty_label = '— No linked booking —'
        form.fields['invoice'].empty_label = '— No linked invoice —'
        return form

    if request.method == 'POST':
        form = _scoped(PaymentForm(request.POST))
        if form.is_valid():
            p = form.save(commit=False)
            p.organization = org

            # Ownership guard
            if org and p.booking_id and p.booking.property.organization_id != org.id:
                form.add_error('booking', 'That booking does not belong to your organization.')
            elif org and p.invoice_id and p.invoice.organization_id != org.id:
                form.add_error('invoice', 'That invoice does not belong to your organization.')
            else:
                p.save()

                # Sync booking.amount_paid
                if p.booking:
                    p.booking.amount_paid = (p.booking.amount_paid or Decimal('0')) + p.amount
                    p.booking.save()

                # Sync invoice.amount_paid and status
                if p.invoice:
                    p.invoice.amount_paid = (p.invoice.amount_paid or Decimal('0')) + p.amount
                    if p.invoice.balance <= 0:
                        p.invoice.status = 'paid'
                    p.invoice.save()

                messages.success(request, 'Payment recorded.')
                return redirect('bnb_payment_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = _scoped(PaymentForm())

    return render(request, 'bnb/payment_form.html', {
        'form': form,
        'bookings': (
            Booking.objects
            .filter(property__organization=org)
            .select_related('property')
            if org else Booking.objects.none()
        ),
        'invoices': (
            Invoice.objects
            .filter(organization=org)
            if org else Invoice.objects.none()
        ),
    })
    
    
# ---------------------------------------------------------------------------
#  STAFF — LIST
# ---------------------------------------------------------------------------
@login_required
def staff_list(request):
    org = _org(request)
    staff = (
        StaffMember.objects
        .filter(organization=org)
        .select_related('property', 'user')
        .order_by('full_name')
    )
    return render(request, 'bnb/staff_list.html', {'staff': staff})


# ---------------------------------------------------------------------------
#  STAFF — ADD
# ---------------------------------------------------------------------------
@login_required
def staff_add(request):
    org = _org(request)

    def _scoped_form(data=None, instance=None):
        form = StaffMemberForm(data, instance=instance)
        # Scope property dropdown to this org
        form.fields['property'].queryset = (
            Property.objects.filter(organization=org).order_by('name')
            if org else Property.objects.none()
        )
        # Scope user dropdown to users within this org's memberships.
        # Adjust the related_name below to match your accounts app.
        try:
            from accounts.models import Membership  # or whatever links users to orgs
            user_ids = (
                Membership.objects
                .filter(organization=org)
                .values_list('user_id', flat=True)
            )
            form.fields['user'].queryset = (
                form.fields['user'].queryset.filter(pk__in=user_ids)
            )
        except Exception:
            # If the accounts app shape differs, just leave the default queryset.
            pass
        return form

    if request.method == 'POST':
        form = _scoped_form(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.organization = org
            # Belt-and-braces: ensure the chosen property belongs to this org
            if org and obj.property_id:
                if obj.property.organization_id != org.id:
                    form.add_error('property', 'That property does not belong to your organization.')
                    messages.error(request, 'Please correct the errors below.')
                    return render(request, 'bnb/staff_form.html', {
                        'form': form,
                        'properties': Property.objects.filter(organization=org) if org else Property.objects.none(),
                    })
            obj.save()
            messages.success(request, 'Staff member added.')
            return redirect('bnb_staff_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = _scoped_form()

    return render(request, 'bnb/staff_form.html', {
        'form': form,
        'properties': Property.objects.filter(organization=org) if org else Property.objects.none(),
    })


# ---------------------------------------------------------------------------
#  STAFF — EDIT
# ---------------------------------------------------------------------------
@login_required
def staff_edit(request, staff_id):
    org = _org(request)
    s = get_object_or_404(StaffMember, id=staff_id, organization=org)

    def _scoped_form(data=None, instance=None):
        form = StaffMemberForm(data, instance=instance)
        form.fields['property'].queryset = (
            Property.objects.filter(organization=org).order_by('name')
            if org else Property.objects.none()
        )
        try:
            from accounts.models import Membership
            user_ids = (
                Membership.objects
                .filter(organization=org)
                .values_list('user_id', flat=True)
            )
            form.fields['user'].queryset = (
                form.fields['user'].queryset.filter(pk__in=user_ids)
            )
        except Exception:
            pass
        return form

    if request.method == 'POST':
        form = _scoped_form(request.POST, instance=s)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.organization = org
            if org and obj.property_id:
                if obj.property.organization_id != org.id:
                    form.add_error('property', 'That property does not belong to your organization.')
                    messages.error(request, 'Please correct the errors below.')
                    return render(request, 'bnb/staff_form.html', {
                        'form': form,
                        'staff': s,
                        'properties': Property.objects.filter(organization=org) if org else Property.objects.none(),
                    })
            obj.save()
            messages.success(request, 'Staff member updated.')
            return redirect('bnb_staff_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = _scoped_form(instance=s)

    return render(request, 'bnb/staff_form.html', {
        'form': form,
        'staff': s,
        'properties': Property.objects.filter(organization=org) if org else Property.objects.none(),
    })
    

# ============================================================
#  REVIEWS
# ============================================================
@login_required
def review_list(request):
    reviews = (
        Review.objects
        .filter(organization=_org(request))
        .select_related('property')
    )
    avg = reviews.aggregate(a=Avg('rating'))['a'] or 0
    return render(request, 'bnb/review_list.html', {
        'reviews': reviews,
        'avg_rating': round(avg, 2),
    })


@login_required
def review_add(request):
    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            r = form.save(commit=False)
            r.organization = _org(request)
            r.save()
            _notify(
                organization=r.organization,
                event='bnb.review.created',
                subject=f"New review ({r.rating}★) for {r.property.name}",
                body=r.comment or '',
            )
            messages.success(request, 'Review added.')
            return redirect('bnb_review_list')
    else:
        form = ReviewForm()
    return render(request, 'bnb/review_form.html', {'form': form})


# ============================================================
#  REPORTS
# ============================================================@login_required
def reports_dashboard(request):
    org = _org(request)
    today = timezone.now().date()
    month_ago = today - timedelta(days=30)

    bookings = (
        Booking.objects.filter(property__organization=org)
        if org else Booking.objects.none()
    )
    props = (
        Property.objects.filter(organization=org)
        if org else Property.objects.none()
    )

    # ---------- Bookings by source · 30d ----------
    by_source_qs = list(
        bookings
        .filter(created_at__date__gte=month_ago)
        .values('source')
        .annotate(
            count=Count('id'),
            total=Sum('total_amount'),
        )
        .order_by('-count')
    )
    source_labels = dict(Booking.SOURCE)
    total_sources_count = sum(s['count'] for s in by_source_qs) or 1
    for s in by_source_qs:
        s['label'] = source_labels.get(s['source'], s['source'])
        s['pct'] = round(s['count'] / total_sources_count * 100, 1)

    # ---------- By property (revenue from real revenue statuses only) ----------
    by_property = list(
        props.annotate(
            booking_count=Count(
                'bookings',
                filter=Q(bookings__status__in=REVENUE_STATUSES),
            ),
            revenue=Sum(
                'bookings__total_amount',
                filter=Q(bookings__status__in=REVENUE_STATUSES),
            ),
        ).order_by('-revenue')
    )
    max_property_revenue = max(
        (float(p.revenue or 0) for p in by_property), default=0,
    ) or 1.0
    for p in by_property:
        p.pct_bar = round(float(p.revenue or 0) / max_property_revenue * 100, 1)

    # ---------- Headline totals ----------
    total_bookings_30d = bookings.filter(
        created_at__date__gte=month_ago,
    ).count()
    total_revenue_30d = (
        bookings
        .filter(
            created_at__date__gte=month_ago,
            status__in=REVENUE_STATUSES,
        )
        .aggregate(t=Sum('total_amount'))['t']
    ) or Decimal('0.00')

    return render(request, 'bnb/reports_dashboard.html', {
        'by_source': by_source_qs,
        'by_property': by_property,
        'total_bookings_30d': total_bookings_30d,
        'total_revenue_30d': total_revenue_30d,
        'source_count': len(by_source_qs),
        'properties_count': len(by_property),
    })


# ============================================================
#  SECTION LANDING VIEWS
# ============================================================
@login_required
def properties_home(request):
    org = _org(request)

    props = (
        Property.objects.filter(organization=org)
        .select_related('category', 'listing')
        if org else Property.objects.none()
    )

    props_count       = props.count()
    active_props      = props.filter(is_active=True).count()
    inactive_props    = props_count - active_props

    unpublished_props = props.filter(listing__isnull=True).count()

    listing_status = {
        'approved':    0,
        'pending':     0,
        'unpublished': 0,
        'draft':       0,
        'rejected':    0,
    }
    try:
        from marketplace.models import Listing
        rows = (
            Listing.objects
            .filter(organization=org)
            .values('status')
            .annotate(n=Count('id'))
        )
        for row in rows:
            key = (row['status'] or '').strip()
            if key in listing_status:
                listing_status[key] = row['n']
    except Exception:
        pass

    category_breakdown = []
    try:
        rows = (
            props.values('category__name', 'category__slug', 'category__accent', 'category__icon')
            .annotate(n=Count('id'))
            .order_by('-n')
        )
        category_breakdown = list(rows)
    except Exception:
        pass

    recent_props = list(props.order_by('-created_at')[:5])

    context = {
        'props_count':        props_count,
        'active_props_count': active_props,
        'inactive_props_count': inactive_props,
        'unpublished_props_count': unpublished_props,
        'listing_status': listing_status,
        'category_breakdown': category_breakdown,
        'recent_properties': recent_props,
    }
    return render(request, 'bnb/propertiessub_base.html', context)


# ============================================================
#  SECTION LANDING VIEWS — BOOKINGS
# ============================================================
@login_required
def bookings_home(request):
    """
    Bookings landing page.

    A snapshot of what matters today:
      • Headline counts (total / in-house / arrivals today / pending)
      • A list of today's arrivals
      • Recent bookings for context
      • Quick links into the full list and calendar
    """
    org = _org(request)
    today = timezone.now().date()
    month_start = today.replace(day=1)

    bookings = (
        Booking.objects
        .filter(property__organization=org)
        .select_related('property', 'guest')
        if org else Booking.objects.none()
    )

    # ---- Headline counts ----
    bookings_count = bookings.count()
    in_house       = bookings.filter(status='checked_in').count()
    pending        = bookings.filter(status='pending').count()
    checkouts      = bookings.filter(check_out=today, status='checked_in').count()

    # ---- Today's arrivals (list, not just count) ----
    arrivals = (
        bookings
        .filter(check_in=today, status__in=['pending', 'confirmed'])
        .order_by('property__name', 'guest_name')
    )
    arrivals_count = arrivals.count()

    # ---- Next 5 upcoming arrivals after today ----
    next_arrivals = (
        bookings
        .filter(check_in__gt=today, status__in=['pending', 'confirmed'])
        .order_by('check_in')[:5]
    )

    # ---- Recent bookings (6 for the 3-column grid) ----
    recent = bookings.order_by('-created_at')[:9]
    
    # ---- This-month revenue from confirmed stays ----
    month_revenue = bookings.filter(
        status__in=['confirmed', 'checked_in', 'checked_out'],
        created_at__date__gte=month_start,
    ).aggregate(t=Sum('total_amount'))['t'] or Decimal('0.00')

    # ---- Guest count ----
    guests = Guest.objects.filter(organization=org).count() if org else 0

    return render(request, 'bnb/bookingssub_base.html', {
        'bookings_count':   bookings_count,
        'in_house_count':   in_house,
        'pending_count':    pending,
        'checkouts_today':  checkouts,
        'arrivals_today':   arrivals_count,
        'arrivals':         arrivals,
        'next_arrivals':    next_arrivals,
        'guests_count':     guests,
        'recent_bookings':  recent,
        'month_revenue':    month_revenue,
    })


@login_required
def operations_home(request):
    """
    Operations landing page.

    Snapshot of housekeeping, maintenance, and staff state:
      • Headline counts (open / in progress / done today, urgent, staff)
      • Recent tasks and maintenance requests
      • Staff breakdown by role
    """
    from .models import HousekeepingTask, MaintenanceRequest, StaffMember
    
    org = _org(request)
    
    # Ensure we use local time for "Today"
    now_local = timezone.localtime()
    today = now_local.date()
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    tasks = (
        HousekeepingTask.objects
        .filter(property__organization=org)
        .select_related('property')
        if org else HousekeepingTask.objects.none()
    )
    maint = (
        MaintenanceRequest.objects
        .filter(property__organization=org)
        .select_related('property')
        if org else MaintenanceRequest.objects.none()
    )
    staff = (
        StaffMember.objects
        .filter(organization=org)
        if org else StaffMember.objects.none()
    )

    # ---- Housekeeping counts ----
    open_tasks           = tasks.filter(status='open').count()
    in_progress_tasks    = tasks.filter(status='in_progress').count()
    done_today           = tasks.filter(
        status='done',
        completed_at__gte=today_start,
    ).count()

    # ---- Maintenance counts ----
    open_maint           = maint.exclude(status='resolved').count()
    in_progress_maint    = maint.filter(status='in_progress').count()
    urgent_maint         = maint.filter(
        status__in=['open', 'in_progress'],
        priority__in=['high', 'urgent'],
    ).count()

    # ---- Staff counts ----
    active_staff = staff.filter(is_active=True).count()

    # ---- Staff by role ----
    staff_by_role = []
    try:
        rows = (
            staff
            .filter(is_active=True)
            .values('role')
            .annotate(n=Count('id'))
            .order_by('-n')
        )
        role_labels = dict(StaffMember.ROLE)
        for row in rows:
            role_key = (row['role'] or 'other').strip()
            if row['n']:
                staff_by_role.append({
                    'role': role_key,
                    'label': role_labels.get(role_key, role_key.title()),
                    'count': row['n'],
                })
    except Exception:
        staff_by_role = []

    # ---- Recent items ----
    recent_tasks = list(
        tasks.order_by('-created_at')[:6]
    )
    recent_maintenance = list(
        maint.order_by('-created_at')[:6]
    )

    context = {
        # Housekeeping
        'open_tasks_count':        open_tasks,
        'in_progress_tasks_count': in_progress_tasks,
        'done_today_count':        done_today,

        # Maintenance
        'open_maintenance_count':        open_maint,
        'in_progress_maintenance_count': in_progress_maint,
        'urgent_maintenance_count':      urgent_maint,

        # Staff
        'active_staff_count': active_staff,
        'staff_by_role':      staff_by_role,

        # Lists
        'recent_tasks':       recent_tasks,
        'recent_maintenance': recent_maintenance,
    }
    return render(request, 'bnb/operationssub_base.html', context)



@login_required
def finance_home(request):
    org = _org(request)
    today = timezone.now().date()
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    def qs_for(model, **filters):
        base = model.objects.filter(organization=org) if org else model.objects.none()
        return base.filter(**filters) if filters else base

    bookings_qs = (
        Booking.objects.filter(property__organization=org)
        if org else Booking.objects.none()
    )
    expenses_qs = qs_for(Expense)
    invoices_qs = qs_for(Invoice)
    payments_qs = qs_for(Payment)
    revenues_qs = qs_for(Revenue)

    # ------------------------------------------------------------------
    #  Cash in — money that actually landed
    # ------------------------------------------------------------------
    payments_month = payments_qs.filter(payment_date__gte=month_start)
    cash_in_month = (
        payments_month.aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')

    payments_last_month = payments_qs.filter(
        payment_date__gte=last_month_start,
        payment_date__lt=month_start,
    )
    cash_in_last_month = (
        payments_last_month.aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')

    cash_in_all = (
        payments_qs.aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')

    # Cash in vs last month — % change (only if last month > 0)
    cash_in_delta_pct = None
    if cash_in_last_month > 0:
        cash_in_delta_pct = round(
            float(cash_in_month - cash_in_last_month)
            / float(cash_in_last_month) * 100,
            1,
        )

    # ------------------------------------------------------------------
    #  Cash out — money that actually left
    # ------------------------------------------------------------------
    expenses_month = expenses_qs.filter(expense_date__gte=month_start)
    cash_out_month = (
        expenses_month.aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')

    cash_out_last_month = (
        expenses_qs.filter(
            expense_date__gte=last_month_start,
            expense_date__lt=month_start,
        ).aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')

    cash_out_all = (
        expenses_qs.aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')

    cash_out_delta_pct = None
    if cash_out_last_month > 0:
        cash_out_delta_pct = round(
            float(cash_out_month - cash_out_last_month)
            / float(cash_out_last_month) * 100,
            1,
        )

    # ------------------------------------------------------------------
    #  Net cash this month — the "am I winning?" number
    # ------------------------------------------------------------------
    net_month = cash_in_month - cash_out_month
    net_last_month = cash_in_last_month - cash_out_last_month

    # Visual proportion (for the cash flow bar)
    cash_total = cash_in_month + cash_out_month
    cash_in_pct = (
        round(float(cash_in_month) / float(cash_total) * 100, 1)
        if cash_total else 50
    )
    cash_out_pct = (
        round(float(cash_out_month) / float(cash_total) * 100, 1)
        if cash_total else 50
    )

    # ------------------------------------------------------------------
    #  Bookings this month — how much business landed
    # ------------------------------------------------------------------
    bookings_month = bookings_qs.filter(
        created_at__date__gte=month_start,
    )
    bookings_month_count = bookings_month.count()
    bookings_month_value = (
        bookings_month
        .filter(status__in=REVENUE_STATUSES)
        .aggregate(t=Sum('total_amount'))['t']
    ) or Decimal('0.00')

    # Month-over-month booking count change
    bookings_last_month_count = bookings_qs.filter(
        created_at__date__gte=last_month_start,
        created_at__date__lt=month_start,
    ).count()

    bookings_delta = (
        bookings_month_count - bookings_last_month_count
        if bookings_last_month_count else None
    )

    # ------------------------------------------------------------------
    #  Outstanding — bookings that owe you money
    # ------------------------------------------------------------------
    unpaid_bookings = (
        bookings_qs
        .filter(status__in=OUTSTANDING_STATUSES)
        .select_related('property')
        .order_by('check_in')
    )
    unpaid_bookings_list = [
        b for b in unpaid_bookings if b.balance > 0
    ][:6]
    outstanding_balance = sum(
        (b.balance for b in unpaid_bookings if b.balance > 0),
        Decimal('0.00'),
    )
    outstanding_count = sum(
        1 for b in unpaid_bookings if b.balance > 0
    )

    # Days overdue per unpaid booking (check-out in the past = overdue)
    for b in unpaid_bookings_list:
        if b.check_out < today:
            b.days_overdue = (today - b.check_out).days
        else:
            b.days_overdue = 0

    # ------------------------------------------------------------------
    #  Invoices — the operational summary
    # ------------------------------------------------------------------
    invoices_total = invoices_qs.count()
    invoices_paid = invoices_qs.filter(status='paid').count()
    invoices_overdue = invoices_qs.filter(status='overdue').count()

    # Money still owed via invoices
    invoice_outstanding_amount = sum(
        (i.balance for i in invoices_qs.filter(
            status__in=INVOICE_OPEN_STATUSES,
        ) if i.balance > 0),
        Decimal('0.00'),
    )

    # ------------------------------------------------------------------
    #  Revenue vs expenses — full picture (kept for KPI cards)
    # ------------------------------------------------------------------
    total_revenue = (
        bookings_qs
        .filter(status__in=REVENUE_STATUSES)
        .aggregate(t=Sum('total_amount'))['t']
    ) or Decimal('0.00')

    total_extra_revenue = (
        revenues_qs.aggregate(t=Sum('amount'))['t']
    ) or Decimal('0.00')

    total_expenses = cash_out_all
    total_profit = total_revenue + total_extra_revenue - total_expenses
    profit_margin = (
        round(
            (total_profit / (total_revenue + total_extra_revenue) * 100), 1
        ) if (total_revenue + total_extra_revenue) else 0
    )

    # Legacy keys other templates may reference
    month_revenue = (
        bookings_month
        .filter(status__in=REVENUE_STATUSES)
        .aggregate(t=Sum('total_amount'))['t']
    ) or Decimal('0.00')
    month_expenses = cash_out_month
    month_profit = month_revenue - month_expenses
    month_margin = (
        round((month_profit / month_revenue * 100), 1) if month_revenue else 0
    )

    # ------------------------------------------------------------------
    #  Recent activity — payments landing, not payments being sent
    # ------------------------------------------------------------------
    recent_payments = (
        payments_qs
        .select_related('booking', 'invoice')
        .order_by('-payment_date', '-created_at')[:5]
    )
    recent_expenses = (
        expenses_qs
        .select_related('category', 'property')
        .order_by('-expense_date', '-created_at')[:5]
    )

    # ------------------------------------------------------------------
    #  Property breakdown — where money comes from
    # ------------------------------------------------------------------
    top_properties = list(
        bookings_qs
        .filter(status__in=REVENUE_STATUSES)
        .values('property__name', 'property__id')
        .annotate(
            revenue=Sum('total_amount'),
            bookings_count=Count('id'),
        )
        .order_by('-revenue')[:5]
    )

    # Add pct against total_revenue for bar width
    for row in top_properties:
        if total_revenue:
            row['pct'] = round(
                float(row['revenue']) / float(total_revenue) * 100, 1
            )
        else:
            row['pct'] = 0

    # ------------------------------------------------------------------
    #  Expense category breakdown
    # ------------------------------------------------------------------
    by_category = (
        expenses_qs
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:5]
    )
    max_category_total = (
        by_category[0]['total'] if by_category else Decimal('0.00')
    ) or Decimal('0.00')

    for row in by_category:
        if max_category_total:
            row['pct'] = round(
                float(row['total']) / float(max_category_total) * 100, 1
            )
        else:
            row['pct'] = 0

    # ------------------------------------------------------------------
    #  Context
    # ------------------------------------------------------------------
    context = {
        # KPIs
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'total_profit': total_profit,
        'profit_margin': profit_margin,
        'month_revenue': month_revenue,
        'month_expenses': month_expenses,
        'month_profit': month_profit,
        'month_margin': month_margin,
        'total_extra_revenue': total_extra_revenue,

        # Cash flow
        'cash_in_month': cash_in_month,
        'cash_in_last_month': cash_in_last_month,
        'cash_in_delta_pct': cash_in_delta_pct,
        'cash_in_all': cash_in_all,
        'cash_out_month': cash_out_month,
        'cash_out_last_month': cash_out_last_month,
        'cash_out_delta_pct': cash_out_delta_pct,
        'cash_out_all': cash_out_all,
        'net_month': net_month,
        'net_last_month': net_last_month,
        'cash_in_pct': cash_in_pct,
        'cash_out_pct': cash_out_pct,

        # Bookings this month
        'bookings_month_count': bookings_month_count,
        'bookings_month_value': bookings_month_value,
        'bookings_last_month_count': bookings_last_month_count,
        'bookings_delta': bookings_delta,

        # Outstanding
        'outstanding_balance': outstanding_balance,
        'outstanding_count': outstanding_count,
        'unpaid_bookings_list': unpaid_bookings_list,

        # Invoices
        'invoices_total': invoices_total,
        'invoices_paid': invoices_paid,
        'invoices_overdue': invoices_overdue,
        'invoice_outstanding_amount': invoice_outstanding_amount,

        # Recent
        'recent_payments': recent_payments,
        'recent_expenses': recent_expenses,

        # Breakdowns
        'top_properties': top_properties,
        'by_category': by_category,

        # Legacy safety keys (so other templates don't break)
        'revenue_totals': {},
        'expense_totals': {},
        'profit_totals': {},
    }
    return render(request, 'bnb/financesub_base.html', context)




# ============================================================
#  REPORTS — OVERVIEW
# ============================================================
@login_required
def reports_home(request):
    org = _org(request)
    today = timezone.now().date()
    month_ago = today - timedelta(days=30)
    week_ahead = today + timedelta(days=7)

    bookings = (
        Booking.objects.filter(property__organization=org)
        if org else Booking.objects.none()
    )
    props = (
        Property.objects.filter(organization=org)
        if org else Property.objects.none()
    )
    reviews_qs = (
        Review.objects.filter(organization=org)
        if org else Review.objects.none()
    )

    bookings_30d = bookings.filter(created_at__date__gte=month_ago).count()

    revenue_30d = (
        bookings
        .filter(
            created_at__date__gte=month_ago,
            status__in=REVENUE_STATUSES,
        )
        .aggregate(t=Sum('total_amount'))['t']
    ) or Decimal('0.00')

    total_props = props.count()
    occupied_props = (
        bookings
        .filter(
            check_in__lte=today, check_out__gt=today,
            status__in=['confirmed', 'checked_in'],
        )
        .values('property').distinct().count()
    )
    occupancy_rate = (
        round((occupied_props / total_props * 100), 1) if total_props else 0
    )

    avg_rating = reviews_qs.aggregate(a=Avg('rating'))['a'] or 0

    guests_count = (
        Guest.objects.filter(organization=org).count() if org else 0
    )
    open_maintenance = (
        MaintenanceRequest.objects
        .filter(property__organization=org)
        .exclude(status='resolved').count()
        if org else 0
    )

    by_source_qs = list(
        bookings
        .filter(created_at__date__gte=month_ago)
        .values('source')
        .annotate(count=Count('id'), total=Sum('total_amount'))
        .order_by('-count')
    )
    by_source_total = sum(s['count'] for s in by_source_qs) or 1
    source_labels = dict(Booking.SOURCE)
    for s in by_source_qs:
        s['label'] = source_labels.get(s['source'], s['source'])
        s['pct'] = round(s['count'] / by_source_total * 100, 1)

    by_property = list(
        props.annotate(
            booking_count=Count(
                'bookings',
                filter=Q(bookings__status__in=REVENUE_STATUSES),
            ),
            revenue=Sum(
                'bookings__total_amount',
                filter=Q(bookings__status__in=REVENUE_STATUSES),
            ),
        ).order_by('-revenue')
    )
    max_property_revenue = max(
        (float(p.revenue or 0) for p in by_property), default=0,
    ) or 1.0
    for p in by_property:
        p.pct_bar = round(float(p.revenue or 0) / max_property_revenue * 100, 1)

    checkins_week = (
        bookings
        .filter(check_in__gte=today, check_in__lte=week_ahead)
        .exclude(status__in=['cancelled', 'no_show'])
        .count()
    )
    checkouts_week = (
        bookings
        .filter(check_out__gte=today, check_out__lte=week_ahead)
        .exclude(status__in=['cancelled', 'no_show'])
        .count()
    )

    return render(request, 'bnb/reportssub_base.html', {
        'bookings_30d': bookings_30d,
        'revenue_30d': revenue_30d,
        'occupancy_rate': occupancy_rate,
        'occupied_props': occupied_props,
        'props_count': total_props,
        'avg_rating': round(avg_rating, 1) if avg_rating else 0,
        'reviews_count': reviews_qs.count(),
        'guests_count': guests_count,
        'open_maintenance': open_maintenance,
        'by_source': by_source_qs,
        'by_source_total': by_source_total,
        'by_property': by_property,
        'checkins_week': checkins_week,
        'checkouts_week': checkouts_week,
    })


# ============================================================
#  REPORTS — OCCUPANCY
# ============================================================
@login_required
def reports_occupancy(request):
    org = _org(request)
    today = timezone.now().date()

    props = (
        Property.objects.filter(organization=org).order_by('name')
        if org else Property.objects.none()
    )
    total_props = props.count()

    period_start = today - timedelta(days=30)
    period_days = 30

    relevant = (
        Booking.objects
        .filter(
            property__organization=org,
            status__in=REVENUE_STATUSES,
            check_in__lte=today,
            check_out__gte=period_start,
        )
        .values('property_id', 'check_in', 'check_out')
        if org else []
    )

    nights_by_prop = defaultdict(int)
    for b in relevant:
        start = max(b['check_in'], period_start)
        end = min(b['check_out'], today + timedelta(days=1))
        nights = max((end - start).days, 0)
        nights_by_prop[b['property_id']] += nights

    property_stats = []
    for p in props:
        nights = min(nights_by_prop.get(p.id, 0), period_days)
        occupancy_pct = round((nights / period_days) * 100, 1) if period_days else 0

        is_occupied = (
            Booking.objects
            .filter(
                property=p,
                check_in__lte=today, check_out__gt=today,
                status__in=['confirmed', 'checked_in'],
            )
            .exists()
        )

        property_stats.append({
            'id': p.id,
            'name': p.name,
            'is_occupied': is_occupied,
            'nights': nights,
            'occupancy_pct': occupancy_pct,
        })

    overall_rate = (
        round(sum(s['occupancy_pct'] for s in property_stats) / len(property_stats), 1)
        if property_stats else 0
    )
    occupied_props = sum(1 for s in property_stats if s['is_occupied'])

    return render(request, 'bnb/reports_occupancy.html', {
        'occupancy_rate': overall_rate,
        'occupied_props': occupied_props,
        'props_count': total_props,
        'available_props': total_props - occupied_props,
        'property_stats': property_stats,
        'period_days': period_days,
    })


# ============================================================
#  REPORTS — REVENUE
# ============================================================
@login_required
def reports_revenue(request):
    org = _org(request)
    today = timezone.now().date()
    month_ago = today - timedelta(days=30)

    bookings = (
        Booking.objects.filter(property__organization=org)
        if org else Booking.objects.none()
    )
    confirmed = bookings.filter(status__in=REVENUE_STATUSES)

    total_revenue = (
        confirmed.aggregate(t=Sum('total_amount'))['t']
    ) or Decimal('0.00')

    revenue_30d = (
        confirmed
        .filter(created_at__date__gte=month_ago)
        .aggregate(t=Sum('total_amount'))['t']
    ) or Decimal('0.00')

    total_bookings = confirmed.count()
    avg_booking_value = (
        total_revenue / total_bookings if total_bookings else Decimal('0.00')
    )

    total_nights = sum(
        (b.nights for b in confirmed.only('check_in', 'check_out')),
    )
    avg_nightly_rate = (
        total_revenue / total_nights if total_nights else Decimal('0.00')
    )

    by_source = list(
        bookings
        .filter(created_at__date__gte=month_ago)
        .values('source')
        .annotate(count=Count('id'), total=Sum('total_amount'))
        .order_by('-total')
    )
    source_labels = dict(Booking.SOURCE)
    for s in by_source:
        s['label'] = source_labels.get(s['source'], s['source'])

    props = (
        Property.objects.filter(organization=org)
        if org else Property.objects.none()
    )
    by_property = list(
        props.annotate(
            booking_count=Count(
                'bookings',
                filter=Q(bookings__status__in=REVENUE_STATUSES),
            ),
            revenue=Sum(
                'bookings__total_amount',
                filter=Q(bookings__status__in=REVENUE_STATUSES),
            ),
        ).order_by('-revenue')
    )
    max_property_revenue = max(
        (float(p.revenue or 0) for p in by_property), default=0,
    ) or 1.0
    for p in by_property:
        p.pct_bar = round(float(p.revenue or 0) / max_property_revenue * 100, 1)

    return render(request, 'bnb/reports_revenue.html', {
        'total_revenue': total_revenue,
        'revenue_30d': revenue_30d,
        'avg_booking_value': avg_booking_value,
        'avg_nightly_rate': avg_nightly_rate,
        'total_bookings': total_bookings,
        'total_nights': total_nights,
        'by_source': by_source,
        'by_property': by_property,
    })


# ============================================================
#  REPORTS — PERFORMANCE
# ============================================================
@login_required
def reports_performance(request):
    org = _org(request)
    today = timezone.now().date()

    bookings = (
        Booking.objects.filter(property__organization=org)
        if org else Booking.objects.none()
    )
    confirmed = bookings.filter(status__in=REVENUE_STATUSES)
    total_revenue = (
        confirmed.aggregate(t=Sum('total_amount'))['t']
    ) or Decimal('0.00')

    props = (
        Property.objects.filter(organization=org).order_by('name')
        if org else Property.objects.none()
    )

    occupied_ids = set(
        bookings
        .filter(
            check_in__lte=today, check_out__gt=today,
            status__in=['confirmed', 'checked_in'],
        )
        .values_list('property_id', flat=True)
        .distinct()
    )

    revenue_by_prop = dict(
        confirmed
        .values('property_id')
        .annotate(t=Sum('total_amount'))
        .values_list('property_id', 't')
    )
    bookings_by_prop = dict(
        bookings
        .values('property_id')
        .annotate(c=Count('id'))
        .values_list('property_id', 'c')
    )
    rating_by_prop = dict(
        Review.objects
        .filter(property__organization=org)
        .values('property_id')
        .annotate(a=Avg('rating'))
        .values_list('property_id', 'a')
        if org else []
    )

    property_stats = []
    for p in props:
        is_occupied = p.id in occupied_ids
        rev = revenue_by_prop.get(p.id) or Decimal('0.00')
        cnt = bookings_by_prop.get(p.id, 0)
        rating = rating_by_prop.get(p.id) or 0
        property_stats.append({
            'id': p.id,
            'name': p.name,
            'occupancy_pct': 100 if is_occupied else 0,
            'is_occupied': is_occupied,
            'booking_count': cnt,
            'revenue': rev,
            'avg_rating': round(float(rating), 1) if rating else 0,
        })

    max_prop_rev = max(
        (float(r['revenue'] or 0) for r in property_stats), default=0,
    ) or 1.0
    for r in property_stats:
        r['rev_pct'] = round(float(r['revenue'] or 0) / max_prop_rev * 100, 1)

    property_stats.sort(key=lambda r: float(r['revenue'] or 0), reverse=True)

    return render(request, 'bnb/reports_performance.html', {
        'bookings_count': bookings.count(),
        'total_revenue': total_revenue,
        'open_maintenance': (
            MaintenanceRequest.objects
            .filter(property__organization=org)
            .exclude(status='resolved').count()
            if org else 0
        ),
        'open_tasks': (
            HousekeepingTask.objects
            .filter(property__organization=org)
            .exclude(status='done').count()
            if org else 0
        ),
        'avg_rating': (
            round(
                Review.objects
                .filter(organization=org)
                .aggregate(a=Avg('rating'))['a'] or 0,
                1,
            ) if org else 0
        ),
        'reviews_count': (
            Review.objects.filter(organization=org).count() if org else 0
        ),
        'properties_count': (
            Property.objects.filter(organization=org).count() if org else 0
        ),
        'guests_count': (
            Guest.objects.filter(organization=org).count() if org else 0
        ),
        'property_stats': property_stats,
    })

# ============================================================
#  SETTINGS
# ============================================================
@login_required
def settings_home(request):
    org = _org(request)

    properties = Property.objects.filter(organization=org) if org else Property.objects.none()
    staff = StaffMember.objects.filter(organization=org) if org else StaffMember.objects.none()

    return render(request, 'bnb/settingssub_base.html', {
        'properties_count': properties.count(),
        'active_properties_count': properties.filter(is_active=True).count(),
        'staff_count': staff.count(),
        'active_staff_count': staff.filter(is_active=True).count(),
        'guests_count': Guest.objects.filter(organization=org).count() if org else 0,
        'categories_count': ExpenseCategory.objects.filter(organization=org).count() if org else 0,
    })


@login_required
def settings_general(request):
    return render(request, 'bnb/settings_general.html', {})


@login_required
def settings_team(request):
    org = _org(request)
    staff = StaffMember.objects.filter(organization=org) if org else StaffMember.objects.none()

    return render(request, 'bnb/settings_team.html', {
        'staff_count': staff.count(),
        'managers_count': staff.filter(role='manager').count(),
        'receptionists_count': staff.filter(role='receptionist').count(),
        'housekeepers_count': staff.filter(role='housekeeper').count(),
        'maintenance_count': staff.filter(role='maintenance').count(),
        'accountants_count': staff.filter(role='accountant').count(),
    })


@login_required
def settings_billing(request):
    org = _org(request)
    today = timezone.now().date()
    month_start = today.replace(day=1)

    bookings_month = Booking.objects.filter(
        property__organization=org,
        created_at__date__gte=month_start,
    ).count() if org else 0

    return render(request, 'bnb/settings_billing.html', {
        'properties_count': Property.objects.filter(organization=org).count() if org else 0,
        'staff_count': StaffMember.objects.filter(organization=org).count() if org else 0,
        'bookings_month': bookings_month,
    })


# ============================================================
#  AMENITIES
# ============================================================
def _amenity_icon_choices():
    return [
        ('wifi',       'Wi-Fi'),
        ('pool',       'Pool'),
        ('parking',    'Parking'),
        ('kitchen',    'Kitchen'),
        ('tv',         'TV'),
        ('ac',         'Air conditioning'),
        ('washer',     'Washer / dryer'),
        ('workspace',  'Workspace'),
        ('pet',        'Pet friendly'),
        ('smoke',      'Smoke alarm'),
        ('security',   'Security'),
        ('gym',        'Gym'),
        ('breakfast',  'Breakfast'),
        ('balcony',    'Balcony'),
        ('garden',     'Garden'),
        ('check',      'Other'),
    ]


def _amenity_category_choices():
    return [
        ('general',   'General'),
        ('comfort',   'Comfort'),
        ('safety',    'Safety'),
        ('outdoor',   'Outdoor'),
        ('kitchen',   'Kitchen'),
        ('services',  'Services'),
    ]


@login_required
def amenities(request):
    org = _org(request)
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()

    qs = (
        Amenity.objects.filter(organization=org)
        if org else Amenity.objects.none()
    )
    if q:
        qs = qs.filter(name__icontains=q)
    if category:
        qs = qs.filter(category=category)

    amenities_list = list(qs.order_by('category', 'display_order', 'name'))
    grouped = []
    for cat, items in groupby(amenities_list, key=lambda a: a.category):
        grouped.append({
            'category': cat,
            'items': list(items),
        })

    try:
        categories = (
            Amenity.objects
            .filter(organization=org)
            .values_list('category', flat=True)
            .distinct()
            .order_by('category')
        )
        categories = [c for c in categories if c]
    except Exception:
        categories = []

    return render(request, 'bnb/amenities.html', {
        'grouped_amenities': grouped,
        'total_count': len(amenities_list),
        'q': q,
        'category': category,
        'categories': categories,
    })


@login_required
def amenity_add(request):
    org = _org(request)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        icon = request.POST.get('icon', 'check').strip() or 'check'
        category = request.POST.get('category', 'general').strip() or 'general'
        display_order = request.POST.get('display_order') or 10
        is_active = request.POST.get('is_active') == '1'

        if not name:
            messages.error(request, 'Amenity name is required.')
        else:
            try:
                Amenity.objects.create(
                    organization=org,
                    name=name,
                    icon=icon,
                    category=category,
                    display_order=int(display_order),
                    is_active=is_active,
                )
                messages.success(request, f'"{name}" added to your amenities.')
                return redirect('bnb_amenities')
            except Exception as e:
                messages.error(request, f'Could not add amenity: {e}')

    return render(request, 'bnb/amenity_form.html', {
        'mode': 'create',
        'icon_choices': _amenity_icon_choices(),
        'category_choices': _amenity_category_choices(),
    })


@login_required
def amenity_edit(request, amenity_id):
    org = _org(request)
    amenity = get_object_or_404(Amenity, id=amenity_id, organization=org)

    if request.method == 'POST':
        amenity.name = request.POST.get('name', amenity.name).strip() or amenity.name
        amenity.icon = request.POST.get('icon', amenity.icon).strip() or 'check'
        amenity.category = request.POST.get('category', amenity.category).strip() or 'general'
        try:
            amenity.display_order = int(request.POST.get('display_order') or amenity.display_order)
        except (TypeError, ValueError):
            pass
        amenity.is_active = request.POST.get('is_active') == '1'
        try:
            amenity.save()
            messages.success(request, f'"{amenity.name}" updated.')
            return redirect('bnb_amenities')
        except Exception as e:
            messages.error(request, f'Could not update: {e}')

    return render(request, 'bnb/amenity_form.html', {
        'mode': 'edit',
        'amenity': amenity,
        'icon_choices': _amenity_icon_choices(),
        'category_choices': _amenity_category_choices(),
    })


@login_required
def amenity_delete(request, amenity_id):
    org = _org(request)
    amenity = get_object_or_404(Amenity, id=amenity_id, organization=org)

    if request.method == 'POST':
        name = amenity.name
        amenity.delete()
        messages.success(request, f'"{name}" removed from your amenities.')
    return redirect('bnb_amenities')


# ============================================================
#  PRICING RULES
# ============================================================
@login_required
def pricing_rules(request):
    org = _org(request)
    q = request.GET.get('q', '').strip()
    scope = request.GET.get('scope', '').strip()
    property_id = request.GET.get('property', '').strip()

    qs = (
        PricingRule.objects
        .filter(organization=org)
        .select_related('applies_to_property')   # ← ✓ matches the model
        if org else PricingRule.objects.none()
    )

    if q:
        qs = qs.filter(
            Q(label__icontains=q) |
            Q(description__icontains=q)
        )
    if scope == 'org':
        qs = qs.filter(property__isnull=True)
    elif scope == 'property':
        qs = qs.filter(property__isnull=False)
    if property_id:
        try:
            qs = qs.filter(property_id=int(property_id))
        except (TypeError, ValueError):
            pass

    rules = list(qs.order_by('rule_type', 'display_order', 'label'))
    grouped = []
    for rtype, items in groupby(rules, key=lambda r: r.rule_type):
        label = dict(PricingRule.RULE_TYPE_CHOICES).get(rtype, rtype.title())
        grouped.append({
            'rule_type': rtype,
            'label': label,
            'items': list(items),
        })

    properties = (
        Property.objects.filter(organization=org)
        if org else Property.objects.none()
    )

    total_count = len(rules)
    org_wide_count = sum(1 for r in rules if r.applies_to_property_id is None)
    per_property_count = total_count - org_wide_count

    return render(request, 'bnb/pricing_rules.html', {
        'grouped_rules': grouped,
        'total_count': total_count,
        'org_wide_count': org_wide_count,
        'per_property_count': per_property_count,
        'q': q,
        'scope': scope,
        'property_id': property_id,
        'properties': properties,
    })


@login_required
def pricing_rule_add(request):
    org = _org(request)
    properties = (
        Property.objects.filter(organization=org)
        if org else Property.objects.none()
    )

    if request.method == 'POST':
        label = request.POST.get('label', '').strip()
        description = request.POST.get('description', '').strip()
        rule_type = request.POST.get('rule_type', 'base').strip() or 'base'
        value_type = request.POST.get('value_type', 'note').strip() or 'note'
        value = request.POST.get('value') or 0
        property_id = request.POST.get('property') or None
        display_order = request.POST.get('display_order') or 10
        is_active = request.POST.get('is_active') == '1'

        if not label:
            messages.error(request, 'Rule label is required.')
        else:
            try:
                prop = None
                if property_id:
                    prop = Property.objects.filter(
                        id=int(property_id), organization=org,
                    ).first()

                PricingRule.objects.create(
                    organization=org,
                    applies_to_property=prop,   # ← ✓ matches model
                    label=label,
                    description=description,
                    rule_type=rule_type,
                    value_type=value_type,
                    value=value,
                    display_order=int(display_order),
                    is_active=is_active,
                )
                messages.success(request, f'"{label}" added to your pricing rules.')
                return redirect('bnb_pricing_rules')
            except Exception as e:
                messages.error(request, f'Could not add rule: {e}')

    return render(request, 'bnb/pricing_rule_form.html', {
        'mode': 'create',
        'properties': properties,
        'rule_type_choices': PricingRule.RULE_TYPE_CHOICES,
        'value_type_choices': PricingRule.VALUE_TYPE_CHOICES,
    })


@login_required
def pricing_rule_edit(request, rule_id):
    org = _org(request)
    rule = get_object_or_404(PricingRule, id=rule_id, organization=org)
    properties = (
        Property.objects.filter(organization=org)
        if org else Property.objects.none()
    )

    if request.method == 'POST':
        rule.label = request.POST.get('label', rule.label).strip() or rule.label
        rule.description = request.POST.get('description', '').strip()
        rule.rule_type = request.POST.get('rule_type', rule.rule_type).strip() or rule.rule_type
        rule.value_type = request.POST.get('value_type', rule.value_type).strip() or rule.value_type
        try:
            rule.value = request.POST.get('value') or rule.value
        except Exception:
            pass

        property_id = request.POST.get('property') or None
        rule.applies_to_property = None
        if property_id:
            rule.applies_to_property = Property.objects.filter(
                id=int(property_id), organization=org,
            ).first()

        try:
            rule.display_order = int(request.POST.get('display_order') or rule.display_order)
        except (TypeError, ValueError):
            pass

        rule.is_active = request.POST.get('is_active') == '1'

        try:
            rule.save()
            messages.success(request, f'"{rule.label}" updated.')
            return redirect('bnb_pricing_rules')
        except Exception as e:
            messages.error(request, f'Could not update: {e}')

    return render(request, 'bnb/pricing_rule_form.html', {
        'mode': 'edit',
        'rule': rule,
        'properties': properties,
        'rule_type_choices': PricingRule.RULE_TYPE_CHOICES,
        'value_type_choices': PricingRule.VALUE_TYPE_CHOICES,
    })


@login_required
def pricing_rule_delete(request, rule_id):
    org = _org(request)
    rule = get_object_or_404(PricingRule, id=rule_id, organization=org)

    if request.method == 'POST':
        label = rule.label
        rule.delete()
        messages.success(request, f'"{label}" removed from your pricing rules.')
    return redirect('bnb_pricing_rules')


@login_required
def pricing_rule_toggle(request, rule_id):
    org = _org(request)
    rule = get_object_or_404(PricingRule, id=rule_id, organization=org)

    rule.is_active = not rule.is_active
    rule.save(update_fields=['is_active', 'updated_at'])
    state = 'enabled' if rule.is_active else 'disabled'
    messages.success(request, f'"{rule.label}" {state}.')
    return redirect('bnb_pricing_rules')


# ============================================================
#  EXPENSE CATEGORIES — CRUD
# ============================================================
from django import forms as django_forms
from django.db.models import Count


class _ExpenseCategoryForm(django_forms.ModelForm):
    """Small inline ModelForm — no need to add to forms.py."""
    class Meta:
        model = ExpenseCategory
        fields = ['name', 'description', 'is_recurring']
        widgets = {
            'name': django_forms.TextInput(attrs={'placeholder': 'e.g. Cleaning'}),
            'description': django_forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._organization = organization
        # Duplicate-name check is per-org
        if organization is not None:
            self.fields['name'].widget.attrs['autocomplete'] = 'off'

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise django_forms.ValidationError('Name is required.')
        if self._organization is not None:
            qs = ExpenseCategory.objects.filter(
                organization=self._organization, name__iexact=name,
            )
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise django_forms.ValidationError(
                    f'A category named "{name}" already exists.'
                )
        return name


@login_required
def expense_category_list(request):
    org = _org(request)
    if org is None:
        messages.error(request, 'No organization linked to your account.')
        return redirect('dashboard')

    categories = (
        ExpenseCategory.objects
        .filter(organization=org)
        .annotate(expense_count=Count('expenses'))
        .order_by('name')
    )

    return render(request, 'bnb/expense_category_list.html', {
        'categories': categories,
        'total_count': categories.count(),
    })


@login_required
def expense_category_add(request):
    org = _org(request)
    if org is None:
        messages.error(request, 'No organization linked to your account.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = _ExpenseCategoryForm(request.POST, organization=org)
        if form.is_valid():
            cat = form.save(commit=False)
            cat.organization = org
            cat.save()
            messages.success(request, f'Category "{cat.name}" added.')
            # If user arrived from the expense form, send them back
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('bnb_expense_category_list')
    else:
        form = _ExpenseCategoryForm(organization=org)

    return render(request, 'bnb/expense_category_form.html', {
        'form': form,
        'mode': 'create',
        'category': None,
        'next': request.GET.get('next', ''),
    })


@login_required
def expense_category_edit(request, pk):
    org = _org(request)
    cat = get_object_or_404(ExpenseCategory, pk=pk, organization=org)

    if request.method == 'POST':
        form = _ExpenseCategoryForm(request.POST, instance=cat, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category updated.')
            return redirect('bnb_expense_category_list')
    else:
        form = _ExpenseCategoryForm(instance=cat, organization=org)

    return render(request, 'bnb/expense_category_form.html', {
        'form': form,
        'mode': 'edit',
        'category': cat,
        'next': '',
    })


@login_required
def expense_category_delete(request, pk):
    org = _org(request)
    cat = get_object_or_404(ExpenseCategory, pk=pk, organization=org)

    if request.method == 'POST':
        name = cat.name
        # Detach from expenses so the records remain (as "Uncategorised")
        cat.expenses.update(category=None)
        cat.delete()
        messages.success(request, f'Category "{name}" removed.')
    return redirect('bnb_expense_category_list')