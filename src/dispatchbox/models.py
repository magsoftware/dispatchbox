#!/usr/bin/env python3
"""Data models for outbox events."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Literal, Optional


@dataclass
class OutboxEvent:
    """Data class representing an outbox event from the database."""

    id: Optional[int]
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: Dict[str, Any]
    status: Literal["pending", "retry", "done", "dead"]
    attempts: int
    next_run_at: datetime
    created_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutboxEvent":
        """
        Create OutboxEvent from dictionary (e.g., from database row).

        Args:
            data: Dictionary with event data

        Returns:
            OutboxEvent instance
        """
        next_run_at = data.get("next_run_at")
        if next_run_at is None:
            raise ValueError("next_run_at is required")

        return cls(
            id=data.get("id"),
            aggregate_type=data.get("aggregate_type", ""),
            aggregate_id=data.get("aggregate_id", ""),
            event_type=data.get("event_type", ""),
            payload=data.get("payload", {}),
            status=data.get("status", "pending"),
            attempts=data.get("attempts", 0),
            next_run_at=next_run_at,
            created_at=data.get("created_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert OutboxEvent to dictionary with JSON-serializable values.

        Returns:
            Dictionary representation of the event with datetime objects
            converted to ISO 8601 strings
        """
        result = {
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "status": self.status,
            "attempts": self.attempts,
            "next_run_at": (
                self.next_run_at.isoformat() if isinstance(self.next_run_at, datetime) else self.next_run_at
            ),
        }
        if self.id is not None:
            result["id"] = self.id
        if self.created_at is not None:
            result["created_at"] = (
                self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
            )
        return result
