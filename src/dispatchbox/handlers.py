#!/usr/bin/env python3
"""Event handlers for outbox events."""

import time
from typing import Callable, Dict, Any


def send_email(payload: Dict[str, Any]) -> None:
    """Send email notification."""
    time.sleep(0.2)
    print(f"[send_email] email sent to {payload['customerId']}")


def push_to_crm(payload: Dict[str, Any]) -> None:
    """Push data to CRM system."""
    time.sleep(0.1)
    print(f"[push_to_crm] CRM updated for order {payload['orderId']}")


def record_analytics(payload: Dict[str, Any]) -> None:
    """Record analytics data."""
    time.sleep(0.05)
    print(f"[record_analytics] analytics recorded for order {payload['orderId']}")


# Registry of event handlers
HANDLERS: Dict[str, Callable[[Dict[str, Any]], None]] = {
    "order.created": send_email,
    "order.created.analytics": record_analytics,
    "order.created.crm": push_to_crm,
}

