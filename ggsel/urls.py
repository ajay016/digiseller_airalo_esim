from django.urls import path
from .import views





urlpatterns = [
    path('sync_ggsel_products/', views.sync_ggsel_products, name='sync_ggsel_products'),
    # path('api/variant_duplicate_texts/', views.variant_duplicate_texts, name='variant_duplicate_texts'),
    
    # # path("webhook-test/", views.digiseller_webhook_test, name="digiseller_webhook_test"),
    # # path("webhook-callback/", views.digiseller_webhook_callback, name="digiseller_webhook_callback"),
    
    path("order-confirmation/", views.ggseller_deliver, name="ggseller_deliver"),
    
    # path("order_sample/", views.order_sample, name="order_sample"),
    # path("order_sample/", views.order_sample, name="order_sample"),
]