from django.urls import path
from .import views





urlpatterns = [
    path('sync_esim_products/', views.sync_esim_products, name='sync_esim_products'),
    path('api/variant_duplicate_texts/', views.variant_duplicate_texts, name='variant_duplicate_texts'),
]