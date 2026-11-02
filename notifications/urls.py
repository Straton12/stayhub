# notifications/urls.py
from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('',              views.inbox,           name='inbox'),
    path('health/',       views.health,          name='health'),
    path('<int:pk>/',     views.detail,          name='detail'),
    path('<int:pk>/read/', views.mark_read,      name='mark_read'),
    path('mark-all-read/', views.mark_all_read,  name='mark_all_read'),
    path('api/unread/',    views.unread_count,   name='unread_count'),
]