from django.contrib import admin
from esim.models import *




# @admin.register(DigisellerOrder)
# class DigisellerOrderAdmin(admin.ModelAdmin):
#     list_display = (
#         'order_id',
#         'product',
#         'variant',
#         'airalo_package',
#         'buyer_email',
#         'purchase_amount',
#         'purchase_currency',
#         'status',
#         'is_my_product',
#         'created_at',
#     )
#     list_filter = (
#         'status',
#         'purchase_currency',
#         'product',
#         'variant',
#         'is_my_product',
#         'created_at',
#     )
#     search_fields = (
#         'order_id',
#         'buyer_email',
#         'cart_uid',
#         'error_message',
#     )
#     readonly_fields = (
#         'raw_payload',
#         'created_at',
#         'updated_at',
#     )
#     date_hierarchy = 'created_at'
#     ordering = ['-created_at']
