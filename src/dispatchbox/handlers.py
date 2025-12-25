#!/usr/bin/env python3
"""Event handlers for outbox events."""

import time
from typing import Any, Callable, Dict

from loguru import logger


def send_email(payload: Dict[str, Any]) -> None:
    """Send email notification."""
    time.sleep(0.2)
    logger.info("Email sent to customer {}", payload.get("customerId", "unknown"))


def push_to_crm(payload: Dict[str, Any]) -> None:
    """Push data to CRM system."""
    time.sleep(0.1)
    logger.info("CRM updated for order {}", payload.get("orderId", "unknown"))


def record_analytics(payload: Dict[str, Any]) -> None:
    """Record analytics data."""
    time.sleep(0.05)
    logger.info("Analytics recorded for order {}", payload.get("orderId", "unknown"))


# Registry of event handlers
HANDLERS: Dict[str, Callable[[Dict[str, Any]], None]] = {
    "order.created": send_email,
    "order.created.analytics": record_analytics,
    "order.created.crm": push_to_crm,
}
