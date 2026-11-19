"""Unit Tests: Domain State Machine Transitions.

Validates the pure domain state machine logic in complete isolation from I/O.
"""

import pytest

from app.core.exceptions import InvalidStateTransitionException
from app.core.state_machine import (
    VALID_TRANSITIONS,
    PaymentStatus,
    get_allowed_transitions,
    validate_transition,
)


@pytest.mark.unit
class TestStateMachineUnit:
    """Test Suite ID: TS-SM-UNIT

    Validates finite state machine transition rules and domain invariant enforcement.
    """

    def test_tc_sm_001_valid_transitions_pass(self):
        """Test ID: TC-SM-001

        Scenario: Verify all permissible state transitions execute without raising exceptions.
        Preconditions: System state machine loaded with valid transition map.
        Input Data: Source state and legal target state pairs.
        Expected Result: validate_transition returns None without raising an error.
        Actual Result: Verified via unit execution.
        Status: PASS
        """
        valid_pairs = [
            (PaymentStatus.CREATED, PaymentStatus.AUTHORIZED),
            (PaymentStatus.CREATED, PaymentStatus.FAILED),
            (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED),
            (PaymentStatus.AUTHORIZED, PaymentStatus.CANCELLED),
            (PaymentStatus.CAPTURED, PaymentStatus.SETTLED),
            (PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED),
            (PaymentStatus.CAPTURED, PaymentStatus.REFUNDED),
            (PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.PARTIALLY_REFUNDED),
            (PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED),
            (PaymentStatus.SETTLED, PaymentStatus.PARTIALLY_REFUNDED),
            (PaymentStatus.SETTLED, PaymentStatus.REFUNDED),
        ]
        for src, dst in valid_pairs:
            # Must not raise
            validate_transition(src, dst, payment_id="pay_test_unit")

    @pytest.mark.parametrize(
        "src,dst",
        [
            (PaymentStatus.CREATED, PaymentStatus.CAPTURED),
            (PaymentStatus.CREATED, PaymentStatus.CANCELLED),
            (PaymentStatus.AUTHORIZED, PaymentStatus.REFUNDED),
            (PaymentStatus.AUTHORIZED, PaymentStatus.CREATED),
            (PaymentStatus.CAPTURED, PaymentStatus.CANCELLED),
            (PaymentStatus.CAPTURED, PaymentStatus.AUTHORIZED),
            (PaymentStatus.CANCELLED, PaymentStatus.CAPTURED),
            (PaymentStatus.CANCELLED, PaymentStatus.AUTHORIZED),
            (PaymentStatus.REFUNDED, PaymentStatus.CAPTURED),
            (PaymentStatus.REFUNDED, PaymentStatus.AUTHORIZED),
            (PaymentStatus.FAILED, PaymentStatus.AUTHORIZED),
            (PaymentStatus.FAILED, PaymentStatus.CAPTURED),
        ],
    )
    def test_tc_sm_002_illegal_transitions_raise_exception(self, src: PaymentStatus, dst: PaymentStatus):
        """Test ID: TC-SM-002

        Scenario: Verify illegal lifecycle transitions raise InvalidStateTransitionException.
        Preconditions: Target state is not in the allowed transition set for the source state.
        Input Data: Invalid transition pair (src, dst).
        Expected Result: InvalidStateTransitionException raised with status_code=409.
        Actual Result: Verified via unit execution.
        Status: PASS
        """
        with pytest.raises(InvalidStateTransitionException) as exc_info:
            validate_transition(src, dst, payment_id="pay_test_invalid")

        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "invalid_state_transition"
        assert exc_info.value.details["current_status"] == src.value
        assert exc_info.value.details["attempted_status"] == dst.value

    def test_tc_sm_003_terminal_states_have_empty_allowed_transitions(self):
        """Test ID: TC-SM-003

        Scenario: Verify terminal states (REFUNDED, CANCELLED, FAILED) allow zero transitions.
        Preconditions: None.
        Input Data: Terminal state enums.
        Expected Result: get_allowed_transitions returns an empty list.
        Actual Result: Verified via unit execution.
        Status: PASS
        """
        for terminal in [PaymentStatus.REFUNDED, PaymentStatus.CANCELLED, PaymentStatus.FAILED]:
            allowed = get_allowed_transitions(terminal)
            assert allowed == [], f"Terminal state {terminal} should allow no transitions"
