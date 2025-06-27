from esim.models import *

def get_package_operator_stats():
    total_operators = Operator.objects.count()
    total_packages = Package.objects.count()

    packages_with_variant = Package.objects.filter(digiseller_variants__isnull=False).distinct().count()
    packages_without_variant = total_packages - packages_with_variant

    return {
        "total_operators": total_operators,
        "total_packages": total_packages,
        "packages_with_variant": packages_with_variant,
        "packages_without_variant": packages_without_variant,
    }
