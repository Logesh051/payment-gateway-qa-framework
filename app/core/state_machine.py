"""Domain State Machine & Lifecycle Transitions.

Defines the finite state machine for payments, enforcing legal state
transitions and rejecting invalid operational mutations with HTTP 409 Conflict.
"""

from enum import Enum
from typing import Dict, List, Set

from app.core.exceptions import InvalidStateTransitionException


class PaymentStatus(str, Enum):
    """Payment lifecycle states."""

    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    SETTLED = "SETTLED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


# Explicit state transition map: State -> Set of allowed next states
VALID_TRANSITIONS: Dict[PaymentStatus, Set[PaymentStatus]] = {
    PaymentStatus.CREATED: {
        PaymentStatus.AUTHORIZED,
        PaymentStatus.FAILED,
    },
    PaymentStatus.AUTHORIZED: {
        PaymentStatus.CAPTURED,
        PaymentStatus.CANCELLED,
    },
    PaymentStatus.CAPTURED: {
        PaymentStatus.SETTLED,
        PaymentStatus.PARTIALLY_REFUNDED,
        PaymentStatus.REFUNDED,
    },
    PaymentStatus.PARTIALLY_REFUNDED: {
        PaymentStatus.PARTIALLY_REFUNDED,
        PaymentStatus.REFUNDED,
    },
    # Terminal states have no valid subsequent transitions
    PaymentStatus.SETTLED: {
        PaymentStatus.PARTIALLY_REFUNDED,
        PaymentStatus.REFUNDED,
    },
    PaymentStatus.REFUNDED: set(),
    PaymentStatus.CANCELLED: set(),
    PaymentStatus.FAILED: set(),
}


def get_allowed_transitions(current_status: PaymentStatus) -> List[str]:
    """Return a list of allowed next state names for a given current state."""
    return [s.value for s in VALID_TRANSITIONS.get(current_status, set())]


def validate_transition(current: PaymentStatus, target: PaymentStatus, payment_id: str) -> None:
    """Validate whether transitioning from current to target status is permitted.

    Raises:
        InvalidStateTransitionException: If the transition is illegal.
    """
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionException(
            payment_id=payment_id,
            current_status=current.value,
            attempted_status=target.value,
            allowed_transitions=[s.value for s in allowed],
        )
