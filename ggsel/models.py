from django.db import models
from esim.models import *






class GgselProduct(models.Model):
    id_goods    = models.PositiveIntegerField(unique=True)
    name_goods  = models.CharField(max_length=512)
    info_goods  = models.TextField(blank=True, null=True)
    add_info    = models.TextField(blank=True, null=True)
    price       = models.DecimalField(max_digits=12, decimal_places=2)
    currency    = models.CharField(max_length=10)
    cnt_sell    = models.IntegerField()
    price_usd   = models.DecimalField(max_digits=12, decimal_places=2)
    price_rur   = models.DecimalField(max_digits=12, decimal_places=2)
    price_eur   = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.name_goods} ({self.id_goods})"


class GgselVariant(models.Model):
    product                  = models.ForeignKey(
        GgselProduct,
        on_delete=models.CASCADE,
        related_name="variants"
    )
    variant_value            = models.PositiveIntegerField()  # from `value`
    text                     = models.CharField(max_length=500)
    default                  = models.BooleanField(default=False)
    modify                   = models.CharField(max_length=50, blank=True, null=True)
    modify_value             = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    modify_value_default     = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    modify_type              = models.CharField(max_length=10, blank=True, null=True)
    visible                  = models.BooleanField(default=True)
    
    airalo_package       = models.ForeignKey(
                                'esim.Package',
                                on_delete=models.SET_NULL,
                                null=True,   # ← allow blank until you map
                                blank=True,  # ← allow admin/UI to save unmapped
                                related_name="ggsel_variants"
                            )

    class Meta:
        unique_together = ("product", "variant_value")

    def __str__(self):
        return f"{self.product.id_goods} → {self.text}"
    
    
class GgselFailedEntry(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    reason    = models.TextField()
    data      = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] {self.reason[:50]}"
    
    
class GgselOrder(models.Model):
    STATUS_CHOICES = [
        ('received', 'Received'),
        ('invalid',  'Invalid / Skipped'),
        ('processing', 'Processing'),
        ('failed',   'Failed'),
        ('completed','Completed'),
    ]
    GGSEL_TRANSACTION_STATUS_CHOICES = [
        (1, 'Not Verified'),
        (2, 'Delivered'),
        (3, 'Delivery Confirmed'),
        (4, 'Refuted'),
        (5, 'Delivery Pending'),
    ]

    # Raw webhook fields
    order_id       = models.PositiveIntegerField(unique=True)        # ID_I
    product        = models.ForeignKey(
                        'GgselProduct',
                        on_delete=models.PROTECT,
                        related_name='orders'
                    )
    variant        = models.ForeignKey(
                        'GgselVariant',
                        on_delete=models.PROTECT,
                        related_name='orders'
                    )
    airalo_package = models.ForeignKey(
                        'esim.Package',
                        on_delete=models.PROTECT,
                        related_name='ggsel_orders'
                    )
    # Buyer info
    buyer_email           = models.EmailField(null=True, blank=True)
    buyer_ip              = models.GenericIPAddressField(null=True, blank=True)
    buyer_payment_method  = models.CharField(max_length=50, blank=True, null=True)

    # Full Ggsel purchase-info snapshot
    purchase_amount       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    purchase_currency     = models.CharField(max_length=10, blank=True, null=True)
    purchase_date         = models.DateTimeField(null=True, blank=True)
    invoice_state         = models.IntegerField(null=True, blank=True)
    raw_payload           = models.JSONField()  # store the entire content dict for auditing
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1.0)
    
    airalo_order      = models.OneToOneField(
                            AiraloOrder, on_delete=models.SET_NULL,
                            null=True, blank=True, related_name='ggsel_order')

    # Cart & tracking
    cart_uid              = models.CharField(max_length=100, blank=True, null=True)
    is_my_product         = models.BooleanField(default=True)

    # Processing
    status                = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    ggsel_transaction_status = models.IntegerField(choices=GGSEL_TRANSACTION_STATUS_CHOICES, default=1)
    error_message         = models.TextField(blank=True, null=True)
    
    unique_code           = models.CharField(max_length=16, null=True, blank=True)
    order_info_received   = models.BooleanField(default=False)
    payment_verified      = models.BooleanField(default=False)
    task_enqueued         = models.BooleanField(default=False)

    created_at            = models.DateTimeField(default=timezone.now)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Ggsel Order"
        verbose_name_plural = "Ggsel Orders"

    def __str__(self):
        return f"Order {self.order_id} ({self.get_status_display()})"
    
    
class GgselFailedOrder(models.Model):
    unique_code = models.CharField(max_length=255, unique=True,null=True)
    order_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    status = models.CharField(max_length=100, default="pending")  # e.g., 'pending', 'success', 'error'
    retry_count   = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.order_id)
