"""JSON Schemas for Contract & Envelope Validation (jsonschema).

Defines expected JSON structures according to RESTful API specifications.
"""

PAYMENT_SUCCESS_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "merchant_id",
        "amount_cents",
        "currency",
        "status",
        "captured",
        "card_last4",
        "card_brand",
        "created_at",
        "updated_at",
    ],
    "properties": {
        "id": {"type": "string", "pattern": "^pay_[a-zA-Z0-9]+$"},
        "merchant_id": {"type": "string"},
        "amount_cents": {"type": "integer", "minimum": 50},
        "currency": {"type": "string", "enum": ["USD", "EUR", "GBP", "CAD", "INR"]},
        "status": {
            "type": "string",
            "enum": [
                "CREATED",
                "AUTHORIZED",
                "CAPTURED",
                "SETTLED",
                "PARTIALLY_REFUNDED",
                "REFUNDED",
                "CANCELLED",
                "FAILED",
            ],
        },
        "captured": {"type": "boolean"},
        "card_last4": {"type": "string", "minLength": 4, "maxLength": 4},
        "card_brand": {"type": "string"},
        "failure_code": {"type": ["string", "null"]},
        "failure_message": {"type": ["string", "null"]},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
    },
}

REFUND_SUCCESS_SCHEMA = {
    "type": "object",
    "required": [
        "refund_id",
        "payment_id",
        "amount_refunded_cents",
        "remaining_balance_cents",
        "payment_status",
        "status",
        "created_at",
    ],
    "properties": {
        "refund_id": {"type": "string", "pattern": "^ref_[a-zA-Z0-9]+$"},
        "payment_id": {"type": "string", "pattern": "^pay_[a-zA-Z0-9]+$"},
        "amount_refunded_cents": {"type": "integer", "minimum": 1},
        "remaining_balance_cents": {"type": "integer", "minimum": 0},
        "payment_status": {"type": "string", "enum": ["PARTIALLY_REFUNDED", "REFUNDED"]},
        "status": {"type": "string", "enum": ["COMPLETED"]},
        "created_at": {"type": "string"},
    },
}

ERROR_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message", "details", "timestamp"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
                "timestamp": {"type": "string"},
            },
        }
    },
}

LEDGER_SUMMARY_SCHEMA = {
    "type": "object",
    "required": [
        "merchant_id",
        "currency",
        "available_balance_cents",
        "total_debits_cents",
        "total_credits_cents",
        "is_balanced",
        "entry_count",
    ],
    "properties": {
        "merchant_id": {"type": "string"},
        "currency": {"type": "string"},
        "available_balance_cents": {"type": "integer"},
        "total_debits_cents": {"type": "integer", "minimum": 0},
        "total_credits_cents": {"type": "integer", "minimum": 0},
        "is_balanced": {"type": "boolean"},
        "entry_count": {"type": "integer", "minimum": 0},
    },
}
