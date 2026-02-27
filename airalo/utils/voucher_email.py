import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def build_voucher_email_html(*, customer_email: str, booking_reference: str, package_id: str, codes: list[str]) -> tuple[str, str, str]:
    subject = "Your eSIM Voucher Code(s)"

    codes_html = "".join(
        f"""
        <div style="padding: 10px 12px; border: 1px solid #e5e7eb; border-radius: 10px; margin-bottom: 10px;
                    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
                    font-size: 16px; letter-spacing: .5px; background: #f9fafb;">
            {code}
        </div>
        """
        for code in codes
    )

    html = f"""
    <div style="background:#f3f4f6; padding: 24px;">
        <div style="max-width: 640px; margin: 0 auto; background: #ffffff; border-radius: 14px;
                    border: 1px solid #e5e7eb; overflow: hidden;">
            <div style="padding: 18px 20px; background: #0ea5e9;">
                <div style="font-family: Inter, Arial, sans-serif; font-weight: 700; font-size: 18px; color: #ffffff;">
                    Nomadly — Voucher Delivery
                </div>
                <div style="font-family: Inter, Arial, sans-serif; font-size: 13px; color: rgba(255,255,255,.9); margin-top: 4px;">
                    Booking reference: <b>{booking_reference}</b>
                </div>
            </div>

            <div style="padding: 20px;">
                <div style="font-family: Inter, Arial, sans-serif; font-size: 15px; color: #111827; line-height: 1.45;">
                    Here are your eSIM voucher code(s) for:
                </div>

                <div style="margin-top: 10px; margin-bottom: 14px; font-family: Inter, Arial, sans-serif; font-size: 14px; color:#374151;">
                    <b>Package:</b> {package_id}<br/>
                    <b>Email:</b> {customer_email}
                </div>

                {codes_html}

                <div style="margin-top: 14px; font-family: Inter, Arial, sans-serif; font-size: 13px; color: #6b7280; line-height: 1.5;">
                    If you have any issues using these codes, reply to this email and we’ll help.
                </div>
            </div>

            <div style="padding: 14px 20px; border-top: 1px solid #e5e7eb; background: #fafafa;">
                <div style="font-family: Inter, Arial, sans-serif; font-size: 12px; color: #6b7280;">
                    © {booking_reference} — Nomadly
                </div>
            </div>
        </div>
    </div>
    """

    text = (
        f"Your eSIM voucher code(s)\n\n"
        f"Booking reference: {booking_reference}\n"
        f"Package: {package_id}\n\n"
        f"Codes:\n- " + "\n- ".join(codes) + "\n\n"
        f"If you have any issues, reply to this email."
    )

    from_email = settings.DEFAULT_FROM_EMAIL
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