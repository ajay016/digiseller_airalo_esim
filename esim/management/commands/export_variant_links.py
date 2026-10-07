"""
python manage.py export_variant_links [--output variant_links.json]

Writes every Digiseller and GGsel option ("variant") that is linked to a
provider package to one JSON file, for the NEW marketplace (esim_website) to
re-create the same links with

    python manage.py marketplace_rebuild_mappings --input variant_links.json --apply

READ-ONLY: nothing in this project is changed. The file holds no credentials
and no buyer data - listing ids, option values and texts, and the package each
option sells, by the package's own id (package_id) and provider, which is how
the new server finds it. Primary keys travel for provenance only.
Same format as the new project's marketplace_export_mappings (version 1).
"""
import json
import os
from datetime import datetime, timezone

from django.core.management.base import BaseCommand

from esim.models import DigisellerVariant
from ggsel.models import GgselVariant

SOURCES = (("digiseller", DigisellerVariant), ("ggsel", GgselVariant))


def link_entry(channel, variant):
    package = variant.airalo_package
    product = variant.product
    market = getattr(product, "market", None)
    return {
        "channel": channel,
        "seller_id": None,
        "market_id": getattr(market, "market_id", None),
        "product_external_id": product.id_goods,
        "product_name": product.name_goods,
        "variant_value": variant.variant_value,
        "variant_text": variant.text,
        "provider": package.provider,
        "package_external_id": package.package_id,
        "package_title": package.title,
        "package_data": package.data,
        "package_days": package.day,
        "legacy_ids": {"variant_pk": variant.pk, "package_pk": package.pk},
    }


class Command(BaseCommand):
    help = "Export the option -> package links for the new marketplace (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="variant_links.json",
                            help="File to write (default: variant_links.json in the current folder)")

    def handle(self, *args, **options):
        entries, totals = [], {}
        for channel, model in SOURCES:
            everything = model.objects.all()
            linked = (everything.filter(airalo_package__isnull=False)
                      .select_related("product", "airalo_package")
                      .order_by("product__id_goods", "variant_value"))
            rows = [link_entry(channel, v) for v in linked]
            entries.extend(rows)
            totals[channel] = {
                "listings": everything.values("product_id").distinct().count(),
                "variants": everything.count(),
                "linked": len(rows),
            }

        payload = {
            "version": 1,
            "source": "old-marketplace",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "channels": [c for c, _ in SOURCES],
            "totals": totals,
            "count": len(entries),
            "entries": entries,
        }
        path = options["output"]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        self.stdout.write("Old marketplace - variant -> package links")
        for channel, t in totals.items():
            self.stdout.write(f"  {channel:<11} {t['linked']:>5} linked of {t['variants']:>5} options "
                              f"({t['listings']} listings)")
        self.stdout.write(f"  {'total':<11} {len(entries):>5} linked")
        self.stdout.write(self.style.SUCCESS(f"Written to {os.path.abspath(path)}"))
