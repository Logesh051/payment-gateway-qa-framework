# Payment Gateway Reliability & QA Testing Framework

A beginner-to-intermediate project that tests a simulated payment service. It uses dummy card values only and never processes real payments.

## What it does
1. Accepts a payment request through a REST API.
2. Simulates a successful or declined payment.
3. Saves the transaction in SQLite.
4. Returns payment details for verification.
5. Uses an idempotency key to prevent duplicate records.

## Technologies
- Python – application and test code
- FastAPI – payment API
- SQLite – transaction storage
- Pytest – automated tests
- HTTPX / FastAPI TestClient – sends test requests

## Test scenarios
| Scenario | Expected result |
|---|---|
| Valid payment | SUCCESS |
| Declined dummy card | FAILED |
| Zero or negative amount | Request rejected |
| Invalid card number | Request rejected |
| Missing idempotency key | Request rejected |
| Same request and same key repeated | Original payment returned; no duplicate |
| Same key reused with changed details | Request rejected |
| Retrieve existing payment | Stored details returned |
| Retrieve unknown payment | 404 Not Found |
| Database check | Stored amount and status match API response |

## Run on Windows PowerShell
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/docs` to try the API. A dummy card ending in `0002` simulates a decline; other valid dummy cards simulate success.

Run tests:
```powershell
pytest
```
Create HTML report:
```powershell
pytest --html=report.html --self-contained-html
```

## API endpoints
- `POST /payments` – create a simulated payment; requires `Idempotency-Key`.
- `GET /payments/{payment_id}` – retrieve a payment.
- `GET /health` – health check.

Amounts are whole Indian rupees in this learning version. Use dummy card values only.
