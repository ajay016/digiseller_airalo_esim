import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def build_voucher_email_content(
        *,
        customer_email: str,
        booking_reference: str,
        package_id: str,
        codes: list[str]
    ) -> tuple[str, str, str]:
    subject = "Your eSIM Voucher Code(s)"

    context = {
        "customer_email": customer_email,
        "booking_reference": booking_reference,
        "package_id": package_id,
        "codes": codes,
        "brand_name": "Nomadly",
    }

    text = render_to_string("airalo/emails/voucher_email.txt", context)
    html = render_to_string("airalo/emails/voucher_email.html", context)

    return subject, text, html


def send_voucher_email(*, to_email: str, subject: str, text: str, html: str) -> None:
    logger.info("📧 [VoucherEmail] preparing email to=%s subject=%s", to_email, subject)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)

    logger.info("📧 [VoucherEmail] sent to=%s", to_email)


def send_voucher_email_to_customer(
        *,
        to_email: str,
        customer_email: str,
        booking_reference: str,
        package_id: str,
        codes: list[str]
    ) -> None:
    subject, text, html = build_voucher_email_content(
        customer_email=customer_email,
        booking_reference=booking_reference,
        package_id=package_id,
        codes=codes,
    )

    send_voucher_email(
        to_email=to_email,
        subject=subject,
        text=text,
        html=html,
    )