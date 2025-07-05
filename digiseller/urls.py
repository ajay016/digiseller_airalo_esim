from django.urls import path
from .import views





urlpatterns = [
    path('sync_esim_products/', views.sync_esim_products, name='sync_esim_products'),
    path('api/variant_duplicate_texts/', views.variant_duplicate_texts, name='variant_duplicate_texts'),
    
    # path("webhook-test/", views.digiseller_webhook_test, name="digiseller_webhook_test"),
    # path("webhook-callback/", views.digiseller_webhook_callback, name="digiseller_webhook_callback"),
    
    # path("order-confirmation/", views.digiseller_deliver, name="digiseller_deliver"),
]