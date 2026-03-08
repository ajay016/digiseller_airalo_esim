from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from .models import *





class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'
    fk_name = 'user'


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal Info'), {
            'fields': ('user_id', 'username', 'phone_number', 'address')
        }),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        (_('User Type & Status'), {
            'fields': ('user_type', 'user_status')
        }),
        (_('Important Dates'), {
            'fields': ('last_login',)
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'user_id', 'username', 'phone_number', 'user_type', 'user_status'),
        }),
    )

    list_display = ('email', 'username', 'user_type', 'user_status', 'is_staff')
    list_filter = ('user_type', 'user_status', 'is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('email', 'username', 'phone_number', 'user_id')
    ordering = ('email',)
    filter_horizontal = ('groups', 'user_permissions',)
    inlines = (UserProfileInline,)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'city', 'state', 'country', 'job_title')
    search_fields = ('user__email', 'user__username', 'city', 'state', 'country', 'job_title')
    
    

@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'country_code', 'image_preview')
    search_fields = ('title', 'country_code', 'slug')
    prepopulated_fields = {'slug': ('title',)}

    def image_preview(self, obj):
        if obj.image_url:
            return f'<img src="{obj.image_url}" width="50" height="30" style="object-fit:cover;" />'
        return "-"
    image_preview.allow_tags = True
    image_preview.short_description = 'Flag'
    
    
class OperatorCountryInline(admin.TabularInline):
    model = OperatorCountry
    extra = 1


class CoverageInline(admin.TabularInline):
    model = Coverage
    extra = 1


class NetworkInline(admin.TabularInline):
    model = Network
    extra = 1


@admin.register(Operator)
class OperatorAdmin(admin.ModelAdmin):
    list_display = ('title', 'operator_id', 'country', 'is_prepaid', 'is_roaming', 'is_kyc_verify', 'rechargeability', 'flag_preview')
    list_filter = ('country', 'is_prepaid', 'is_roaming', 'is_kyc_verify', 'rechargeability')
    search_fields = ('title', 'operator_id', 'country__title')
    inlines = [OperatorCountryInline, CoverageInline]

    def flag_preview(self, obj):
        if obj.image_url:
            return mark_safe(f'<img src="{obj.image_url}" width="40" height="25" style="object-fit:cover;" />')
        return "-"
    flag_preview.short_description = "Logo"


@admin.register(Coverage)
class CoverageAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'operator')
    search_fields = ('name', 'code', 'operator__title')
    inlines = [NetworkInline]


@admin.register(Network)
class NetworkAdmin(admin.ModelAdmin):
    list_display = ('name', 'coverage')
    search_fields = ('name', 'coverage__name')


@admin.register(OperatorCountry)
class OperatorCountryAdmin(admin.ModelAdmin):
    list_display = ('title', 'country_code', 'operator', 'flag_preview')
    search_fields = ('title', 'country_code', 'operator__title')

    def flag_preview(self, obj):
        if obj.image_url:
            return mark_safe(f'<img src="{obj.image_url}" width="40" height="25" style="object-fit:cover;" />')
        return "-"
    flag_preview.short_description = "Flag"
    
    
@admin.register(APN)
class APNAdmin(admin.ModelAdmin):
    list_display = ('operator', 'ios_apn_type', 'ios_apn_value', 'android_apn_type', 'android_apn_value')
    search_fields = ('operator__title', 'ios_apn_type', 'android_apn_type')


class PackageAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "package_id",
        "operator",
        "type",
        "price",
        "day",
        "is_unlimited",
        "is_fair_usage_policy",
    )
    list_filter = (
        "operator",
        "type",
        "is_unlimited",
        "is_fair_usage_policy",
    )
    search_fields = (
        "title",
        "operator__title",
        "package_id",
    )
    readonly_fields = (
        "qr_installation",
        "manual_installation",
        "fair_usage_policy",
    )


# IMPORTANT:
# Do NOT register Package if you want separated menus only.
# If you still want to keep "Packages" in sidebar, uncomment this line.
# admin.site.register(Package, PackageAdmin)


class BasePackageAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "package_id",
        "operator",
        "type",
        "price",
        "day",
        "is_unlimited",
        "is_fair_usage_policy",
    )
    list_filter = (
        "operator",
        "type",
        "is_unlimited",
        "is_fair_usage_policy",
    )
    search_fields = (
        "title",
        "operator__title",
        "package_id",
    )
    readonly_fields = (
        "qr_installation",
        "manual_installation",
        "fair_usage_policy",
    )


@admin.register(AiraloPackage)
class AiraloPackageAdmin(BasePackageAdmin):
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(provider=PackageProvider.AIRALO)

    def save_model(self, request, obj, form, change):
        obj.provider = PackageProvider.AIRALO
        super().save_model(request, obj, form, change)


@admin.register(SmartEsimPackage)
class SmartEsimPackageAdmin(BasePackageAdmin):
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(provider=PackageProvider.ESIM_ACCESS)

    def save_model(self, request, obj, form, change):
        obj.provider = PackageProvider.ESIM_ACCESS
        super().save_model(request, obj, form, change)


# If Package was registered somewhere else, hide it so you only see Airalo + Smart eSIMs
try:
    admin.site.unregister(Package)
except admin.sites.NotRegistered:
    pass


# Optional: hide the original Package model so you only see the two separated menus
# admin.site.unregister(Package)


@admin.register(AiraloToken)
class AiraloTokenAdmin(admin.ModelAdmin):
    list_display = ('access_token_short', 'expires_at', 'is_valid_now')
    readonly_fields = ('access_token', 'expires_at')

    def access_token_short(self, obj):
        return obj.access_token[:30] + "..." if len(obj.access_token) > 30 else obj.access_token
    access_token_short.short_description = 'Access Token'

    def is_valid_now(self, obj):
        from django.utils import timezone
        return obj.expires_at > timezone.now()
    is_valid_now.boolean = True
    is_valid_now.short_description = 'Is Valid'


@admin.register(AiraloFailedPackage)
class AiraloFailedPackageAdmin(admin.ModelAdmin):
    list_display = ('reason', 'timestamp')
    readonly_fields = ('reason', 'timestamp', 'data')
    search_fields = ('reason',)
    
    
class DigisellerVariantInline(admin.TabularInline):
    model = DigisellerVariant
    extra = 1
    fields = (
        'variant_value', 'text', 'default', 'modify',
        'modify_value', 'modify_value_default', 'modify_type', 'visible', 'airalo_package'
    )
    show_change_link = True

@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ('name', 'market_id')
    search_fields = ('name',)
    ordering = ('name',)

@admin.register(DigisellerProduct)
class DigisellerProductAdmin(admin.ModelAdmin):
    list_display = ('id_goods', 'name_goods', 'price', 'currency', 'cnt_sell', 'market')
    search_fields = ('id_goods', 'name_goods', 'currency')
    list_filter = ('currency', 'market')
    readonly_fields = ('price_usd', 'price_rur', 'price_eur')
    inlines = [DigisellerVariantInline]


@admin.register(DigisellerVariant)
class DigisellerVariantAdmin(admin.ModelAdmin):
    list_display = (
        'product', 'variant_value', 'text', 'default', 'visible',
        'modify', 'modify_value', 'modify_value_default', 'modify_type', 'airalo_package'
    )
    list_filter = ('visible', 'default', 'modify_type', 'variant_value')
    search_fields = ('product__name_goods', 'text', 'variant_value')
    
    
@admin.register(DigisellerFailedEntry)
class DigisellerFailedEntryAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'short_reason', 'has_data')
    readonly_fields = ('timestamp', 'reason', 'data')
    search_fields = ('reason',)
    ordering = ('-timestamp',)

    def short_reason(self, obj):
        return obj.reason[:70] + ('...' if len(obj.reason) > 70 else '')
    short_reason.short_description = 'Reason'

    def has_data(self, obj):
        return bool(obj.data)
    has_data.boolean = True
    has_data.short_description = 'Has Data'
    
    
class AiraloSimInline(admin.TabularInline):
    model = AiraloSim
    extra = 0
    readonly_fields = ('sim_id', 'iccid', 'lpa', 'qrcode_url', 'is_roaming')
    fields = (
        'sim_id', 'iccid', 'lpa', 'qrcode', 'qrcode_url',
        'direct_apple_installation_url', 'apn_type', 'apn_value', 'is_roaming'
    )
    show_change_link = True


@admin.register(AiraloOrder)
class AiraloOrderAdmin(admin.ModelAdmin):
    list_display = ('airalo_id', 'code', 'package_title', 'price', 'currency', 'created_at_api')
    search_fields = ('airalo_id', 'code', 'package_title')
    list_filter = ('currency', 'type')
    inlines = [AiraloSimInline]
    readonly_fields = ('created_at_api', 'created_at')
    fieldsets = (
        (None, {
            'fields': (
                'airalo_id', 'code', 'currency', 'package_id', 'quantity',
                'type', 'description', 'esim_type', 'validity', 'package_title',
                'data', 'price', 'net_price'
            )
        }),
        ('Installation', {
            'fields': (
                'manual_installation', 'qrcode_installation',
                'installation_guides'
            )
        }),
        ('Meta', {
            'fields': ('raw_payload', 'created_at_api', 'created_at')
        }),
    )


@admin.register(AiraloSim)
class AiraloSimAdmin(admin.ModelAdmin):
    list_display = ('sim_id', 'iccid', 'airalo_order', 'is_roaming', 'created_at')
    search_fields = ('sim_id', 'iccid', 'lpa')
    list_filter = ('is_roaming', 'apn_type')
    readonly_fields = ('created_at',)
    raw_id_fields = ('airalo_order',)


@admin.register(DigisellerOrder)
class DigisellerOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_id', 'digiseller_transaction_status', 'unique_code', 'product', 'variant', 'airalo_package',
        'status', 'purchase_amount', 'purchase_currency',
        'buyer_email', 'purchase_date'
    )
    search_fields = ('order_id', 'buyer_email', 'digiseller_transaction_status', 'unique_code')
    list_filter = ('status', 'purchase_currency', 'invoice_state')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('product', 'variant', 'airalo_package', 'airalo_order')

    fieldsets = (
        (None, {
            'fields': (
                'order_id', 'product', 'unique_code', 'variant', 'airalo_package',
                'quantity', 'is_my_product'
            )
        }),
        ('Buyer Info', {
            'fields': ('buyer_email', 'buyer_ip', 'buyer_payment_method')
        }),
        ('Purchase Info', {
            'fields': (
                'purchase_amount', 'purchase_currency',
                'purchase_date', 'invoice_state'
            )
        }),
        ('Processing', {
            'fields': ('status', 'digiseller_transaction_status', 'esim_email_sent', 'error_message', 'airalo_order')
        }),
        ('Tracking & Meta', {
            'fields': ('cart_uid', 'raw_payload', 'created_at', 'updated_at')
        }),
    )
    


@admin.register(DigisellerFailedOrder)
class DigisellerFailedOrderAdmin(admin.ModelAdmin):
    list_display = ('unique_code', 'status', 'retry_count', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('unique_code',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)

    fieldsets = (
        (None, {
            'fields': ('unique_code', 'status', 'retry_count', 'created_at')
        }),
    )
    
    
class ProductAdItemInline(admin.TabularInline):
    """
    Inline for managing ProductAdItems within the SelectedProductAd admin.
    """
    model = ProductAdItem
    extra = 1
    fields = ('product', 'display_name', 'product_url')


@admin.register(PurchaseDiscountAd)
class PurchaseDiscountAdAdmin(admin.ModelAdmin):
    """
    Admin interface for PurchaseDiscountAd model.
    """
    list_display = ('title', 'discount_text', 'is_active', 'display_order')
    list_filter = ('is_active',)
    search_fields = ('title', 'description', 'discount_text')
    ordering = ('display_order',)
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'is_active', 'display_order')
        }),
        ('Discount Details', {
            'fields': ('discount_text', 'discount_code')
        }),
    )


@admin.register(TravelGuideAd)
class TravelGuideAdAdmin(admin.ModelAdmin):
    """
    Admin interface for TravelGuideAd model.
    """
    list_display = ('title', 'is_active', 'display_order', 'external_link')
    list_filter = ('is_active',)
    search_fields = ('title', 'description')
    ordering = ('display_order',)
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'is_active', 'display_order')
        }),
        ('Guide Content', {
            'fields': ('file', 'external_link')
        }),
    )


@admin.register(SelectedProductAd)
class SelectedProductAdAdmin(admin.ModelAdmin):
    """
    Admin interface for SelectedProductAd model.
    Includes an inline for managing associated products.
    """
    list_display = ('title', 'is_active', 'display_order')
    list_filter = ('is_active',)
    search_fields = ('title', 'description')
    ordering = ('display_order',)
    inlines = [ProductAdItemInline]
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'is_active', 'display_order')
        }),
    )


@admin.register(SocialMediaAd)
class SocialMediaAdAdmin(admin.ModelAdmin):
    """
    Admin interface for SocialMediaAd model.
    """
    list_display = ('title', 'is_active', 'display_order', 'telegram_link')
    list_filter = ('is_active',)
    search_fields = ('title', 'description', 'telegram_link', 'facebook_link')
    ordering = ('display_order',)
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'is_active', 'display_order')
        }),
        ('Social Media Links', {
            'fields': ('telegram_link', 'facebook_link', 'instagram_link', 'youtube_link')
        }),
    )
    
    
class AiraloVoucherCodeInline(admin.TabularInline):
    model = AiraloVoucherCode
    extra = 0
    can_delete = True
    fields = ("package_id", "code", "booking_reference", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ()
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        # Usually you only want these created from API response, not manually.
        return False


@admin.register(AiraloVoucherOrder)
class AiraloVoucherOrderAdmin(admin.ModelAdmin):
    list_display = (
        "booking_reference",
        "codes_count",
        "meta_message",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = ("booking_reference", "meta_message", "codes__code", "codes__package_id")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    readonly_fields = ("created_at", "raw_payload_pretty")
    fields = ("booking_reference", "meta_message", "created_at", "raw_payload_pretty", "raw_payload")

    inlines = (AiraloVoucherCodeInline,)

    def codes_count(self, obj):
        return obj.codes.count()
    codes_count.short_description = "Codes"

    def raw_payload_pretty(self, obj):
        # Lightweight pretty view; keep raw JSONField editable below if you need.
        return format_html("<pre style='white-space: pre-wrap; margin:0;'>{}</pre>", obj.raw_payload)
    raw_payload_pretty.short_description = "Raw payload (preview)"


@admin.register(AiraloVoucherCode)
class AiraloVoucherCodeAdmin(admin.ModelAdmin):
    list_display = (
        "package_id",
        "code",
        "booking_reference",
        "voucher_order",
        "created_at",
    )
    list_filter = ("package_id", "created_at")
    search_fields = ("package_id", "code", "booking_reference", "voucher_order__booking_reference")
    ordering = ("-created_at",)

    raw_id_fields = ("voucher_order",)
    readonly_fields = ("created_at",)

    fieldsets = (
        ("Voucher Code", {
            "fields": ("voucher_order", "package_id", "code", "booking_reference"),
        }),
        ("Timestamps", {
            "fields": ("created_at",),
        }),
    )
    
    
@admin.register(ESIMAccessPackage)
class ESIMAccessPackageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'package_id',
        'name',
        'country',
        'operator',
        'created_at',
        'updated_at',
    )
    search_fields = (
        'package_id',
        'name',
        'country',
        'operator',
    )
    list_filter = (
        'country',
        'operator',
        'created_at',
        'updated_at',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
        'raw_data',
    )
    ordering = ('-created_at',)


@admin.register(ESIMAccessFailedPackage)
class ESIMAccessFailedPackageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'short_reason',
        'timestamp',
        'created_at',
        'updated_at',
    )
    search_fields = (
        'reason',
    )
    list_filter = (
        'timestamp',
        'created_at',
        'updated_at',
    )
    readonly_fields = (
        'timestamp',
        'created_at',
        'updated_at',
        'data',
    )
    ordering = ('-created_at',)

    @admin.display(description='Reason')
    def short_reason(self, obj):
        if not obj.reason:
            return '-'
        return obj.reason[:80]


class ESIMAccessSIMInline(admin.TabularInline):
    model = ESIMAccessSIM
    extra = 0
    fields = (
        'sim_id',
        'iccid',
        'status',
        'package_name',
        'msisdn',
        'activated_at',
        'expired_at',
    )
    readonly_fields = (
        'sim_id',
        'iccid',
        'status',
        'package_name',
        'msisdn',
        'activated_at',
        'expired_at',
        'created_at',
        'updated_at',
    )
    show_change_link = True


@admin.register(ESIMAccessOrder)
class ESIMAccessOrderAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'order_no',
        'esimaccess_id',
        'package_id',
        'package_title',
        'quantity',
        'price',
        'net_price',
        'currency',
        'status',
        'created_at',
    )
    search_fields = (
        'order_no',
        'transaction_id',
        'package_id',
        'package_title',
        'description',
        'esimaccess_id',
    )
    list_filter = (
        'status',
        'currency',
        'type',
        'created_at',
        'updated_at',
        'created_at_api',
    )
    readonly_fields = (
        'created_at_api',
        'created_at',
        'updated_at',
        'raw_payload',
        'installation_guides',
    )
    ordering = ('-created_at',)
    inlines = [ESIMAccessSIMInline]


@admin.register(ESIMAccessSIM)
class ESIMAccessSIMAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'sim_id',
        'iccid',
        'esimaccess_order',
        'package_name',
        'status',
        'msisdn',
        'is_roaming',
        'activated_at',
        'expired_at',
        'created_at',
    )
    search_fields = (
        'sim_id',
        'iccid',
        'imsi',
        'esim_tran_no',
        'msisdn',
        'package_name',
        'activation_code',
        'smdp_address',
        'esimaccess_order__order_no',
    )
    list_filter = (
        'status',
        'is_roaming',
        'duration_unit',
        'apn_type',
        'created_at',
        'updated_at',
        'activated_at',
        'expired_at',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
        'raw_payload',
        'installation_guides',
    )
    autocomplete_fields = ('esimaccess_order',)
    ordering = ('-created_at',)


@admin.register(ESIMAccessFailedOrder)
class ESIMAccessFailedOrderAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'order_no',
        'package_code',
        'digiseller_order',
        'status',
        'retry_count',
        'last_retry_at',
        'timestamp',
        'created_at',
    )
    search_fields = (
        'order_no',
        'package_code',
        'error_message',
        'reason',
        'stack_trace',
    )
    list_filter = (
        'status',
        'timestamp',
        'created_at',
        'updated_at',
        'last_retry_at',
    )
    readonly_fields = (
        'timestamp',
        'created_at',
        'updated_at',
        'payload',
    )
    autocomplete_fields = ('digiseller_order',)
    ordering = ('-created_at',)
    
    

