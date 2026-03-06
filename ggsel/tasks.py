from celery import shared_task
from ggsel.models import GgselFailedOrder, GgselFailedEntry
from ggsel.views import(
    verify_unique_code_and_get_info,
    fetch_seller_goods,
    filter_esim_products,
    save_product_with_variants
)
import logging









MAX_RETRIES = 5

logger = logging.getLogger(__name__)



@shared_task
def retry_all_failed_orders():
    failed_qs = GgselFailedOrder.objects.all()
    for failed in failed_qs:
        try:
            verify_unique_code_and_get_info(failed.unique_code)
            # only delete when that specific code truly succeeds
            failed.delete()
        except Exception:
            failed.retry_count += 1
            failed.status = "error"
            if failed.retry_count >= MAX_RETRIES:
                failed.status = "permanent-failure"
            failed.save()
            
            
            
@shared_task(bind=True)
def sync_ggsel_products_task(self, owner_id=1):
    logger.warning(f"[sync_ggsel_products_task] START owner_id={owner_id}")

    raw_products = fetch_seller_goods(owner_id=owner_id)
    logger.warning(f"[sync_ggsel_products_task] total fetched={len(raw_products)}")

    esim_products = filter_esim_products(raw_products)
    logger.warning(f"[sync_ggsel_products_task] filtered eSIM products={len(esim_products)}")

    saved_ids = []

    for index, prod in enumerate(esim_products, start=1):
        try:
            saved = save_product_with_variants(prod)
            saved_ids.append(saved.id_goods)
            logger.warning(f"[sync_ggsel_products_task] saved product id_goods={saved.id_goods}")
        except Exception as e:
            logger.exception(f"[sync_ggsel_products_task] save_product error id={prod.get('id_goods')}: {e}")
            GgselFailedEntry.objects.create(
                reason=f"save_product error (id {prod.get('id_goods')}): {e}",
                data=prod,
            )

    logger.warning(f"[sync_ggsel_products_task] END saved_count={len(saved_ids)}")

    return {
        "saved_product_ids": saved_ids,
        "saved_count": len(saved_ids),
    }
