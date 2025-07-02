from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.safestring import mark_safe
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
        'title',
        'package_id',  # Fixed missing comma between fields
        'operator',
        'type',
        'price',
        'day',
        'is_unlimited',
        'is_fair_usage_policy',
    )
    list_filter = (
        'operator',
        'type',
        'is_unlimited',
        'is_fair_usage_policy',
    )
    search_fields = (
        'title',
        'operator__title',
        'package_id',
    )
    readonly_fields = (
        'qr_installation',
        'manual_installation',
        'fair_usage_policy',
    )

admin.site.register(Package, PackageAdmin)


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


@admin.register(AiraloPackage)
class AiraloPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'package_id', 'country')
    search_fields = ('name', 'package_id', 'country')


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


@admin.register(DigisellerProduct)
class DigisellerProductAdmin(admin.ModelAdmin):
    list_display = ('id_goods', 'name_goods', 'price', 'currency', 'cnt_sell')
    search_fields = ('id_goods', 'name_goods', 'currency')
    list_filter = ('currency',)
    inlines = [DigisellerVariantInline]
    readonly_fields = ('price_usd', 'price_rur', 'price_eur')


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
    search_fields = ('order_id', 'buyer_email', 'digiseller_transaction_status')
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
            'fields': ('status', 'digiseller_transaction_status', 'error_message', 'airalo_order')
        }),
        ('Tracking & Meta', {
            'fields': ('cart_uid', 'raw_payload', 'created_at', 'updated_at')
        }),
    )