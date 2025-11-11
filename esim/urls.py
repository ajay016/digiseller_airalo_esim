from django.urls import path
from .import views
from ggsel.views import sync_ggsel_products





urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path('sync-data/', views.sync_data, name='sync_data'),
    path('digiseller-products/<int:market_id>', views.digiseller_products, name='digiseller_products'),
    path('digiseller-product/<int:id>', views.digiseller_product, name='digiseller_product'),

    path('ggseller-products', views.ggseller_products, name='ggseller_products'),
    path('ggseller-product/<int:id>', views.ggseller_product, name='ggseller_product'),
    # path('sync_ggsel_products/', sync_ggsel_products, name='sync_ggsel_products'),


    path('get-packages-by-region/', views.get_packages_by_region, name='get_packages_by_region'),
    path('update-variants/', views.update_variants, name='update_variants'),
    path('update-ggseller-variants/', views.update_ggseller_variants, name='update_ggseller_variants'),
    path('api/monthly-order-totals/', views.monthly_order_totals, name='monthly_order_totals'),
    
    path('digiseller-deliver/', views.digiseller_deliver, name='digiseller_deliver'),
    
    path('order-sample/', views.order_sample, name='order_sample'),
    
    # Advertisements
    path('social-media-links/', views.social_media_links, name='social_media_links'),
    
    path('product-ad/', views.product_ad, name='product_ad'),
    path('add-selected-product-ad/', views.add_selected_product_ad, name='add_selected_product_ad'),
    path("get-product-items/<int:ad_id>/", views.get_product_items, name="get_product_items"),
    path("edit-selected-product-ad/", views.edit_selected_product_ad, name="edit_selected_product_ad"),
    path("delete-product-ad/", views.delete_product_ad, name="delete_product_ad"),
    
    path("purchase-discount/", views.purchase_discount, name="purchase_discount"),
    path('add-purchase-discount/', views.add_purchase_discount, name='add_purchase_discount'),
    path('edit-purchase-discount-ad/', views.edit_purchase_discount_ad, name='edit_purchase_discount_ad'),
    path('delete-purchase-discount-ad/', views.delete_purchase_discount_ad, name='delete_purchase_discount_ad'),
    
    path('travel-guide-ad/', views.travel_guide_ad, name='travel_guide_ad'),
    path('add-travel-guide-ad/', views.add_travel_guide_ad, name='add_travel_guide_ad'),
    path('edit-travel-guide-ads/', views.edit_travel_guide_ads, name='edit_travel_guide_ads'),
    path('delete-purchase-discount-ad/', views.delete_purchase_discount_ad, name='delete_purchase_discount_ad'),
    
    path('sponsor-ads/', views.sponsor_ads, name='sponsor_ads'),
    path('add-sponsor-ad/', views.add_sponsor_ad, name='add_sponsor_ad'),
    path('delete-sponsor-ad/', views.delete_sponsor_ad, name='delete_sponsor_ad'),
    path("edit-sponsor-ad/", views.edit_sponsor_ad, name="edit_sponsor_ad"),
]
