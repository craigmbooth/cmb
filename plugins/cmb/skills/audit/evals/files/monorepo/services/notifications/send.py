import logging

logger = logging.getLogger(__name__)


def send_email(to, subject, body):
    """Queue an email for delivery. (Stub implementation.)"""
    logger.info("sending email to %s", to)
    return {"to": to, "subject": subject, "status": "queued"}
