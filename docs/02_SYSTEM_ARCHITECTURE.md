# System Architecture

The project has three parts:

1. **FastAPI application:** Receives a payment request, checks its fields, simulates the payment result, and returns a response.
2. **SQLite database:** Stores payment ID, amount, last four card digits, status, idempotency key, and creation time.
3. **Pytest test suite:** Sends HTTP requests to the API, checks response codes and values, and independently checks selected database records.

## Request flow
```text
Pytest test → HTTP request → FastAPI → validate fields → simulate payment
           → save record in SQLite → API response → Pytest checks result
```

## Main files
| File | Responsibility |
|---|---|
| app/main.py | API endpoints and payment simulation |
| app/schemas.py | Validates request fields and describes responses |
| app/database.py | Creates SQLite table and opens connections |
| tests/conftest.py | Gives each test a separate temporary database |
| tests/test_payment_api.py | Functional and negative API tests |
| tests/test_payment_database.py | Database verification |
