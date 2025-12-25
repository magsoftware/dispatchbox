"""Tests for event handlers."""

from unittest.mock import MagicMock, patch

import pytest

from dispatchbox.handlers import HANDLERS, push_to_crm, record_analytics, send_email


def test_send_email(sample_payload):
    """Test send_email handler."""
    with patch("dispatchbox.handlers.time.sleep"):
        with patch("dispatchbox.handlers.logger") as mock_logger:
            send_email(sample_payload)
            mock_logger.info.assert_called_once()
            # Loguru uses format string and arguments
            format_str = mock_logger.info.call_args[0][0]
            args = mock_logger.info.call_args[0][1:]
            assert "Email sent to customer" in format_str
            assert "C001" in str(args)


def test_push_to_crm(sample_payload):
    """Test push_to_crm handler."""
    with patch("dispatchbox.handlers.time.sleep"):
        with patch("dispatchbox.handlers.logger") as mock_logger:
            push_to_crm(sample_payload)
            mock_logger.info.assert_called_once()
            format_str = mock_logger.info.call_args[0][0]
            args = mock_logger.info.call_args[0][1:]
            assert "CRM updated for order" in format_str
            assert "12345" in str(args)


def test_record_analytics(sample_payload):
    """Test record_analytics handler."""
    with patch("dispatchbox.handlers.time.sleep"):
        with patch("dispatchbox.handlers.logger") as mock_logger:
            record_analytics(sample_payload)
            mock_logger.info.assert_called_once()
            format_str = mock_logger.info.call_args[0][0]
            args = mock_logger.info.call_args[0][1:]
            assert "Analytics recorded for order" in format_str
            assert "12345" in str(args)


def test_send_email_sleeps():
    """Test that send_email calls time.sleep."""
    with patch("dispatchbox.handlers.time.sleep") as mock_sleep:
        send_email({"customerId": "C001"})
        mock_sleep.assert_called_once_with(0.2)


def test_push_to_crm_sleeps():
    """Test that push_to_crm calls time.sleep."""
    with patch("dispatchbox.handlers.time.sleep") as mock_sleep:
        push_to_crm({"orderId": "123"})
        mock_sleep.assert_called_once_with(0.1)


def test_record_analytics_sleeps():
    """Test that record_analytics calls time.sleep."""
    with patch("dispatchbox.handlers.time.sleep") as mock_sleep:
        record_analytics({"orderId": "123"})
        mock_sleep.assert_called_once_with(0.05)


def test_handlers_registry():
    """Test that HANDLERS registry contains expected handlers."""
    assert "order.created" in HANDLERS
    assert "order.created.analytics" in HANDLERS
    assert "order.created.crm" in HANDLERS


def test_handlers_are_callable():
    """Test that all handlers in registry are callable."""
    for event_type, handler in HANDLERS.items():
        assert callable(handler), f"Handler for {event_type} is not callable"


def test_handlers_call_with_payload(sample_payload):
    """Test that handlers can be called with payload."""
    with patch("dispatchbox.handlers.time.sleep"):
        # Should not raise
        HANDLERS["order.created"](sample_payload)
        HANDLERS["order.created.analytics"](sample_payload)
        HANDLERS["order.created.crm"](sample_payload)
