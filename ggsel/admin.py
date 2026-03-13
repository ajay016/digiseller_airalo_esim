from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import (
    GgselProduct,
    GgselVariant,
    GgselOrder,
    GgselFailedEntry,
    GgselFailedOrder
)




# ---
## GgselProduct Admin
# ---

class GgselVariantInline(admin.TabularInline):
    """Inline for showing variants directly on the product admin page."""
    model = GgselVariant
    extra = 0
    fields = ('variant_value', 'text', 'airalo_package', 'default', 'visible', 'modify', 'modify_value')
    readonly_fields = ('variant_value', 'text', 'default', 'modify')

@admin.register(GgselProduct)
class GgselProductAdmin(admin.ModelAdmin):
    list_display = (
        'id_goods',
        'name_goods',
        'price',
        'currency',
        'cnt_sell',
        'display_prices',
    )
    search_fields = ('name_goods', 'id_goods')
    list_filter = ('currency',)
    inlines = [GgselVariantInline]
    fieldsets = (
        (None, {
            'fields': ('id_goods', 'name_goods', 'currency', 'price', 'cnt_sell')
        }),
        ('Detailed Info', {
            'fields': ('info_goods', 'add_info'),
            'classes': ('collapse',),
        }),
        ('Converted Prices', {
            'fields': ('price_usd', 'price_rur', 'price_eur'),
            'classes': ('collapse',),
        }),
    )

    def display_prices(self, obj):
        """Custom column to show converted prices concisely."""
        return f"USD: {obj.price_usd} | RUR: {obj.price_rur} | EUR: {obj.price_eur}"
    display_prices.short_description = 'Converted Prices'

# ---
## GgselVariant Admin
# ---

@admin.register(GgselVariant)
class GgselVariantAdmin(admin.ModelAdmin):
    list_display = (
        'product_link',
        'variant_value',
        'text',
        'airalo_package',
        'default',
        'visible',
        'display_modifier',
    )
    list_select_related = ('product', 'airalo_package')
    search_fields = ('product__name_goods', 'text', 'product__id_goods', 'variant_value')
    list_filter = ('default', 'visible', 'modify_type')
    raw_id_fields = ('product', 'airalo_package') # Useful for better performance with many objects
    
    fieldsets = (
        (None, {
            'fields': ('product', 'variant_value', 'text', 'airalo_package')
        }),
        ('Settings', {
            'fields': ('default', 'visible'),
        }),
        ('Price Modification', {
            'fields': ('modify', 'modify_value', 'modify_value_default', 'modify_type'),
            'classes': ('collapse',),
        }),
    )

    def product_link(self, obj):
        """Link to the parent GgselProduct."""
        # 1. Construct the URL name: 'admin:app_label_model_name_change'
        # Assuming your app_label is 'ggsel' and model name is 'ggselproduct'
        url_name = 'admin:ggsel_ggselproduct_change'
        
        # 2. Reverse the URL
        link_url = reverse(url_name, args=[obj.product.pk])
        
        # 3. Use format_html for safe rendering
        return format_html('<a href="{}">{}</a>',
                           link_url,
                           obj.product.name_goods)
    
    product_link.short_description = 'Product'

    def display_modifier(self, obj):
        """Show price modification details."""
        if obj.modify:
            return f"{obj.modify} {obj.modify_value} ({obj.modify_type})"
        return "None"
    display_modifier.short_description = 'Price Mod'


# ---
## GgselOrder Admin
# ---

@admin.register(GgselOrder)
class GgselOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_id',
        'product',
        'variant',
        'status',
        'ggsel_transaction_status',
        'purchase_amount',
        'purchase_currency',
        'purchase_date',
        'airalo_order',
        'created_at',
    )
    list_select_related = ('product', 'variant', 'airalo_package', 'airalo_order')
    search_fields = ('order_id', 'buyer_email', 'unique_code', 'product__name_goods')
    list_filter = ('status', 'ggsel_transaction_status', 'purchase_currency', 'order_info_received', 'payment_verified')
    readonly_fields = ('raw_payload', 'created_at', 'updated_at', 'airalo_order') # Raw payload for auditing
    raw_id_fields = ('product', 'variant', 'airalo_package') # Useful for better performance

    fieldsets = (
        ('Order Identification', {
            'fields': ('order_id', 'product', 'variant', 'airalo_package', 'airalo_order', 'quantity')
        }),
        ('Status & Processing', {
            'fields': ('status', 'ggsel_transaction_status', 'error_message', 'unique_code',
                       'order_info_received', 'payment_verified', 'task_enqueued'),
        }),
        ('Purchase Details', {
            'fields': ('purchase_amount', 'purchase_currency', 'purchase_date', 'invoice_state'),
        }),
        ('Buyer Info', {
            'fields': ('buyer_email', 'buyer_ip', 'buyer_payment_method'),
            'classes': ('collapse',),
        }),
        ('Tracking', {
            'fields': ('cart_uid', 'is_my_product'),
            'classes': ('collapse',),
        }),
        ('Raw Data', {
            'fields': ('raw_payload',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ---
## Failure Tracking Admins
# ---

@admin.register(GgselFailedEntry)
class GgselFailedEntryAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'reason_preview')
    search_fields = ('reason', 'data')
    readonly_fields = ('timestamp', 'reason', 'data')
    list_filter = ('timestamp',)

    def reason_preview(self, obj):
        """Display the first 100 characters of the reason."""
        return obj.reason[:100] + ('...' if len(obj.reason) > 100 else '')
    reason_preview.short_description = 'Reason'

@admin.register(GgselFailedOrder)
class GgselFailedOrderAdmin(admin.ModelAdmin):
    list_display = ('unique_code', 'status', 'retry_count', 'created_at')
    search_fields = ('unique_code',)
    list_filter = ('status', 'created_at')
    readonly_fields = ('created_at',)
    actions = ['mark_as_pending'] # Example action

    def mark_as_pending(self, request, queryset):
        """Admin action to reset status to pending and allow retries."""
        updated = queryset.update(status='pending', retry_count=0)
        self.message_user(request, f"{updated} failed orders marked as pending for retry.")
    mark_as_pending.short_description = "Mark selected orders as pending for retry"
