# Test Strategy

The test suite treats the FastAPI application as the system under test. It sends HTTP requests through FastAPI TestClient and checks the returned status code and response data.

## Test types
- **Functional testing:** Valid payments and declined dummy cards.
- **Negative testing:** Zero/negative amounts, invalid card numbers, and missing request keys.
- **Duplicate-request testing:** Repeat the same request with the same idempotency key and verify the original payment is returned.
- **API testing:** Check endpoint responses, HTTP codes, and payment lookup.
- **Database verification:** Read the saved SQLite record and compare its amount and status with the API response.

Each test uses a separate temporary SQLite database. Run tests with `pytest`. Create an HTML report with `pytest --html=report.html --self-contained-html`.
