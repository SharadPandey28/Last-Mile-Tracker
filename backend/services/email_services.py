import logging
import resend
from backend.config import get_settings

logger = logging.getLogger(__name__)


STATUS_MESSAGES = {
    "picked_up": "Your package has been picked up and is on its way!",
    "in_transit": "Your package is in transit.",
    "out_for_delivery": "Your package is out for delivery today.",
    "delivered": "Your package has been delivered!",
    "failed": "We attempted delivery but it was unsuccessful. We'll retry soon.",
}

def send_delivery_status_email(to: str, customer_name: str, order_id: str, status: str, tracking_url: str = None):
    message = STATUS_MESSAGES.get(status, f"Your order status is now: {status}")

    html = f"""
    <div style="font-family: sans-serif; max-width: 500px; margin: auto;">
      <h2>Order #{order_id} Update</h2>
      <p>Hi {customer_name},</p>
      <p>{message}</p>
      {f'<p><a href="{tracking_url}">Track your order</a></p>' if tracking_url else ''}
      <p>Thanks for shopping with us!</p>
    </div>
    """

    settings = get_settings()
    resend.api_key = settings.resend_api_key
    sender = settings.email_sender or "delivery@yourdomain.com"
    
    try:
        resend.Emails.send({
            "from": sender,
            "to": to,
            "subject": f"Order #{order_id}: {status.replace('_', ' ').title()}",
            "html": html,
        })
        logger.info(f"Status email sent to {to} for order {order_id} ({status})")
    except Exception as e:
        # Don't let email failure break the request — just log it
        logger.error(f"Failed to send status email for order {order_id}: {e}")