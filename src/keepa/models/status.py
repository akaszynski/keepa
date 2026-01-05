"""Status model."""

from dataclasses import dataclass


@dataclass
class Status:
    """Status model class."""

    tokensLeft: int | None = None
    refillIn: float | None = None
    refillRate: float | None = None
    timestamp: float | None = None
