from celery import shared_task
from ggsel.models import GgselFailedOrder
from ggsel.views import verify_unique_code_and_get_info

MAX_RETRIES = 5

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
