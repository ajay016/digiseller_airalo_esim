from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from django.db.models import Count, Q
import calendar
from esim.models import *

def get_unique_buyer_stats():
    buyer_stats_qs = (
        DigisellerOrder.objects
        .filter(buyer_email__isnull=False)
        .values('buyer_email')
        .annotate(
            total_orders=Count('id'),
            total_amount=Sum('purchase_amount')
        )
        .order_by('-total_amount')
    )

    # Round total_amount to 2 decimal places
    buyer_stats = []
    for buyer in buyer_stats_qs:
        total_amount = buyer['total_amount'] or Decimal('0.00')
        buyer['total_amount'] = total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        buyer_stats.append(buyer)

    total_unique_buyers = len(buyer_stats)

    return buyer_stats, total_unique_buyers



def get_monthly_digiseller_stats():
    orders = (
        DigisellerOrder.objects
        .annotate(month=TruncMonth("created_at"))  # or "purchase_date"
        .values("month")
        .annotate(
            total=Count("id"),
            total_sales=Sum("purchase_amount", filter=Q(digiseller_transaction_status=1)),
            failed=Count("id", filter=~Q(digiseller_transaction_status=1)),
        )
        .order_by("month")
    )

    # Initialize stats
    stats = defaultdict(lambda: {"total": 0, "sales": Decimal("0.00"), "failed": 0})
    for o in orders:
        month_name = o["month"].strftime("%B")  # e.g. "June"
        stats[month_name] = {
            "total": o["total"],
            "sales": o["total_sales"] or Decimal("0.00"),
            "failed": o["failed"],
        }

    # Fill in all 12 months
    months = list(calendar.month_name)[1:]  # ['January', ..., 'December']
    monthly_totals = []
    sales_per_month = []
    failed_orders_per_month = []

    for month in months:
        monthly_totals.append(stats[month]["total"])
        sales_per_month.append(float(stats[month]["sales"]))  # convert Decimal to float
        failed_orders_per_month.append(stats[month]["failed"])

    return {
        "monthly_totals": monthly_totals,
        "sales_per_month": sales_per_month,
        "failed_orders_per_month": failed_orders_per_month,
    }
    

def get_recent_orders():
    orders = (
        DigisellerOrder.objects
        .select_related("product", "variant", "airalo_package")
        .order_by("-created_at")[:10]
    )

    results = []
    for order in orders:
        results.append({
            "order_id": order.order_id,
            "name_goods": order.product.name_goods if order.product else None,
            "variant_text": order.variant.text if order.variant else None,
            "package_id": order.airalo_package.package_id if order.airalo_package else None,
            "buyer_email": order.buyer_email,
            "purchase_amount": float(order.purchase_amount or 0),
            "purchase_date": order.purchase_date,
            "status": order.status,
        })

    return results


def get_digiseller_product_variant_stats():
    total_products = DigisellerProduct.objects.count()
    total_variants = DigisellerVariant.objects.count()

    variants_with_package = DigisellerVariant.objects.filter(airalo_package__isnull=False).count()
    variants_without_package = total_variants - variants_with_package

    return {
        "total_products": total_products,
        "total_variants": total_variants,
        "variants_with_package": variants_with_package,
        "variants_without_package": variants_without_package,
    }
