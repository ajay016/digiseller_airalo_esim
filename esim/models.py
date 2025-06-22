from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager, Group, Permission
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify
from .utils.slug_utils import generate_unique_slug
from django.utils import timezone
from django.core.files.storage import default_storage
from io import BytesIO
from django.core.files.base import ContentFile
from decimal import Decimal





class UserManager(BaseUserManager):
    def create_user(self, email, user_id=None, username=None, phone_number=None, password=None, user_type=3, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        if not password:
            raise ValueError("Password is required")

        email = self.normalize_email(email)
        user = self.model(
            user_id=user_id,
            username=username,
            email=email,
            phone_number=phone_number,
            user_type=user_type,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, user_id=None, username=None, phone_number=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('user_type', 0)

        return self.create_user(
            email=email,
            user_id=user_id or 'admin001',
            username=username or 'admin',
            phone_number=phone_number,
            password=password,
            **extra_fields
        )


class User(AbstractBaseUser, PermissionsMixin):
    USER_TYPE_CHOICES = (
        (0, 'Admin'),
        (1, 'Staff'),
    )

    STATUS_CHOICES = (
        (0, 'Inactive'),
        (1, 'Active'),
        (2, 'Suspended'),
    )

    user_id = models.CharField(unique=True, max_length=15, blank=True, null=True)
    username = models.CharField(unique=True, max_length=150, blank=True, null=True)
    email = models.EmailField(unique=True, max_length=100)
    phone_number = models.CharField(max_length=20, unique=True, blank=True, null=True)
    address = models.CharField(max_length=250, blank=True, null=True)
    user_type = models.IntegerField(choices=USER_TYPE_CHOICES, default=2)
    user_status = models.IntegerField(choices=STATUS_CHOICES, default=1)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    # REQUIRED_FIELDS = ['user_id', 'username', 'phone_number']

    def __str__(self):
        return self.username


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    hire_date = models.DateField(null=True, blank=True)
    job_title = models.CharField(max_length=100, blank=True, null=True)
    skills = models.TextField(blank=True, null=True)
    profile_picture = models.URLField(blank=True, null=True)
    linkedin_profile = models.URLField(blank=True, null=True)
    github_profile = models.URLField(blank=True, null=True)
    biography = models.TextField(blank=True, null=True)
    timezone = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.user.username
    
    
class Country(models.Model):
    slug = models.SlugField()
    country_code = models.CharField(max_length=5)
    title = models.CharField(max_length=100)
    image_url = models.URLField(blank=True, null=True)
    image_width = models.PositiveIntegerField(blank=True, null=True)
    image_height = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        return self.title


class Operator(models.Model):
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name='operators')
    operator_id = models.PositiveIntegerField()
    type = models.CharField(max_length=50, blank=True, null=True)
    is_prepaid = models.BooleanField(default=False)
    title = models.CharField(max_length=100)
    esim_type = models.CharField(max_length=50, blank=True, null=True)
    apn_type = models.CharField(max_length=50, blank=True, null=True)
    apn_value = models.CharField(max_length=100, blank=True, null=True)
    is_roaming = models.BooleanField(default=False)
    plan_type = models.CharField(max_length=50, blank=True, null=True)
    activation_policy = models.CharField(max_length=50, blank=True, null=True)
    is_kyc_verify = models.BooleanField(default=False)
    rechargeability = models.BooleanField(default=False)
    other_info = models.TextField(blank=True, null=True)
    info = models.JSONField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    image_width = models.PositiveIntegerField(blank=True, null=True)
    image_height = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        return self.title


class OperatorCountry(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='available_countries')
    country_code = models.CharField(max_length=5)
    title = models.CharField(max_length=100)
    image_url = models.URLField(blank=True, null=True)
    image_width = models.PositiveIntegerField(blank=True, null=True)
    image_height = models.PositiveIntegerField(blank=True, null=True)

    def __str__(self):
        return f"{self.operator.title} - {self.title}"


class Coverage(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='coverages')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10)

    def __str__(self):
        return f"{self.operator.title} - {self.name}"


class Network(models.Model):
    coverage = models.ForeignKey(Coverage, on_delete=models.CASCADE, related_name='networks')
    name = models.CharField(max_length=100)
    types = models.JSONField(blank=True, null=True)

    def __str__(self):
        return f"{self.coverage.name} - {self.name}"


class APN(models.Model):
    operator = models.OneToOneField(Operator, on_delete=models.CASCADE, related_name='apn_config')
    ios_apn_type = models.CharField(max_length=50, blank=True, null=True)
    ios_apn_value = models.CharField(max_length=100, blank=True, null=True)
    android_apn_type = models.CharField(max_length=50, blank=True, null=True)
    android_apn_value = models.CharField(max_length=100, blank=True, null=True)


class Package(models.Model):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name='packages')
    package_id = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=50)
    price = models.FloatField()
    amount = models.PositiveIntegerField(blank=True, null=True)
    day = models.PositiveIntegerField(blank=True, null=True)
    is_unlimited = models.BooleanField(default=False)
    title = models.CharField(max_length=100)
    short_info = models.TextField(blank=True, null=True)
    qr_installation = models.TextField(blank=True, null=True)
    manual_installation = models.TextField(blank=True, null=True)
    is_fair_usage_policy = models.BooleanField(default=False)
    fair_usage_policy = models.TextField(blank=True, null=True)
    data = models.CharField(max_length=50, blank=True, null=True)
    voice = models.CharField(max_length=50, blank=True, null=True)
    text = models.CharField(max_length=50, blank=True, null=True)
    net_price = models.FloatField(blank=True, null=True)
    prices = models.JSONField(blank=True, null=True)  # includes currencies

    def __str__(self):
        return f"{self.operator.title} - {self.title}"



class AiraloToken(models.Model):
    access_token = models.TextField()
    expires_at = models.DateTimeField()

    def is_valid(self):
        return self.expires_at > timezone.now()

class AiraloPackage(models.Model):
    package_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=255)
    # Add other relevant fields from package data
    raw_data = models.JSONField()

class AiraloFailedPackage(models.Model):
    reason = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    data = models.JSONField(null=True, blank=True)
    


class DigisellerProduct(models.Model):
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


class DigisellerVariant(models.Model):
    product                  = models.ForeignKey(
        DigisellerProduct,
        on_delete=models.CASCADE,
        related_name="variants"
    )
    variant_value            = models.PositiveIntegerField()  # from `value`
    text                     = models.CharField(max_length=255)
    default                  = models.BooleanField(default=False)
    modify                   = models.CharField(max_length=50, blank=True, null=True)
    modify_value             = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    modify_value_default     = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    modify_type              = models.CharField(max_length=10, blank=True, null=True)
    visible                  = models.BooleanField(default=True)
    
    airalo_package       = models.ForeignKey(
                                Package,
                                on_delete=models.SET_NULL,
                                null=True,   # ← allow blank until you map
                                blank=True,  # ← allow admin/UI to save unmapped
                                related_name="digiseller_variants"
                            )

    class Meta:
        unique_together = ("product", "variant_value")

    def __str__(self):
        return f"{self.product.id_goods} → {self.text}"
    
    
class DigisellerFailedEntry(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    reason    = models.TextField()
    data      = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] {self.reason[:50]}"
    
    
