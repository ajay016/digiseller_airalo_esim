from django.urls import path
from .import views





urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path('sync-data/', views.sync_data, name='sync_data'),
    path('digiseller-products/', views.digiseller_products, name='digiseller_products'),
    path('digiseller-product/<int:id>', views.digiseller_product, name='digiseller_product'),
    path('get-packages-by-region/', views.get_packages_by_region, name='get_packages_by_region'),
    path('update-variants/', views.update_variants, name='update_variants'),
    path('api/monthly-order-totals/', views.monthly_order_totals, name='monthly_order_totals'),
    
    path('digiseller-deliver/', views.digiseller_deliver, name='digiseller_deliver'),
]