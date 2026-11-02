"""
URL configuration for stayhub_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# stayhub_project/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # ---------- Core apps ----------
    path('accounts/',    include('accounts.urls')),
    path('bnb/',         include('bnb.urls')),
    path('tours/',       include('tours.urls')),
    path('restaurant/',  include('restaurant.urls')),
    path('laundry/',     include('laundry.urls')),
    path('network/',     include('network.urls')),

    # ---------- Marketplace + guest + payments + notifications ----------
    path('payments/',      include('payments.urls')),
    path('my/',            include('guestaccount.urls')),       # guests
    path('notifications/', include(
        ('notifications.urls', 'notifications'),                 # <-- gives us the namespace
        namespace='notifications',
    )),

    # Marketplace is mounted last because it owns the root '/'
    path('', include('marketplace.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)