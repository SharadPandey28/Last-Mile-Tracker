"""
Notification service — send emails to customers on status changes.

Uses Resend API for email sending.
This module is a pure side-effect module: it never reads from or writes
to the database. It is called exclusively from order_service.py,
never from route handlers.

Setup: Set EMAIL_SENDER and RESEND_API_KEY in .env
"""
from __future__ import annotations

import logging
import resend
from backend.config import get_settings

logger = logging.getLogger(__name__)


def _send(to: str, subject: str, html_body: str) -> None:
    settings = get_settings()
    if not settings.resend_api_key or not settings.email_sender:
        logger.warning("Email credentials not configured. Skipping email send.")
        return
        
    resend.api_key = settings.resend_api_key
    try:
        r = resend.Emails.send({
            "from": settings.email_sender,
            "to": to,
            "subject": subject,
            "html": html_body
        })
        logger.info("Email sent to %s | Subject: %s | ID: %s", to, subject, r.get("id"))
    except Exception as e:
        # Log but never crash the main flow for email failures
        logger.error("Failed to send email: %s", str(e))


def send_status_update_email(
    customer_email: str,
    order_id: str,
    new_status: str,
    notes: str | None = None,
) -> None:
    """Notify the customer of a status change on their order."""
    subject = f"[Last Mile Tracker] Order {order_id} — Status: {new_status}"
    notes_html = f"<p><strong>Note:</strong> {notes}</p>" if notes else ""
    html_body = f"""
    <html><body>
    <h2>Order Status Update</h2>
    <p>Your order <strong>{order_id}</strong> has been updated.</p>
    <p>New status: <strong style="color:#2563eb">{new_status}</strong></p>
    {notes_html}
    <hr>
    <small>Last Mile Delivery Tracker — automated notification</small>
    </body></html>
    """
    _send(customer_email, subject, html_body)


def send_failed_delivery_email(
    customer_email: str,
    order_id: str,
    reason: str | None = None,
) -> None:
    """Notify the customer that delivery failed and they can reschedule."""
    subject = f"[Last Mile Tracker] Delivery Failed — Order {order_id}"
    reason_html = f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
    html_body = f"""
    <html><body>
    <h2>Delivery Attempt Failed</h2>
    <p>We were unable to deliver order <strong>{order_id}</strong>.</p>
    {reason_html}
    <p>You can reschedule delivery by logging into your dashboard and
    submitting a new delivery date.</p>
    <hr>
    <small>Last Mile Delivery Tracker — automated notification</small>
    </body></html>
    """
    _send(customer_email, subject, html_body)


def send_reschedule_confirmation_email(
    customer_email: str,
    order_id: str,
    reschedule_date: str,
) -> None:
    """Confirm that a reschedule request has been received."""
    subject = f"[Last Mile Tracker] Reschedule Confirmed — Order {order_id}"
    html_body = f"""
    <html><body>
    <h2>Reschedule Confirmed</h2>
    <p>Your order <strong>{order_id}</strong> has been rescheduled.</p>
    <p>New delivery attempt date: <strong>{reschedule_date}</strong></p>
    <p>A delivery agent will be assigned shortly.</p>
    <hr>
    <small>Last Mile Delivery Tracker — automated notification</small>
    </body></html>
    """
    _send(customer_email, subject, html_body)
