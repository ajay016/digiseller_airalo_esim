import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class EsimAccessSimEmailRow:
    iccid: str
    qrcode_url: str
    short_url: str
    smdp_address: str
    activation_code: str


def build_esimaccess_delivery_email(
    *,
    customer_email: str,
    customer_name: str,
    package_title: str,
    country: str,
    sims: list[EsimAccessSimEmailRow],
    sharing_access_code: str | None = None,
    sharing_link: str | None = None,
) -> tuple[str, str, str]:
    subject = "Your eSIM is Ready"

    ctx: dict[str, Any] = {
        "company_name": getattr(settings, "COMPANY_NAME", "Nomadly"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", getattr(settings, "DEFAULT_FROM_EMAIL", "")),
        "year": timezone.now().year,
        "customer_name": customer_name or customer_email,
        "package_title": package_title,
        "country": country,
        "sims": sims,
        "sharing_access_code": sharing_access_code,
        "sharing_link": sharing_link,
    }

    html = render_to_string("emails/esimaccess_ready.html", ctx)
    text = ""
    return subject, text, html


def send_esimaccess_delivery_email(*, to_email: str, subject: str, text: str, html: str) -> None:
    logger.info("📧 [ESIMAccessEmail] preparing email to=%s subject=%s", to_email, subject)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)

    logger.info("📧 [ESIMAccessEmail] sent to=%s", to_email)