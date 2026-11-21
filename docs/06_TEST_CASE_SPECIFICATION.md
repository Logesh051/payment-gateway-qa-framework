# Test Case Specification

| ID | Scenario | Input | Expected result |
|---|---|---|---|
| TC-01 | Successful payment | Positive amount and approved dummy card | HTTP 201; status SUCCESS |
| TC-02 | Declined payment | Positive amount and card ending 0002 | HTTP 201; status FAILED |
| TC-03 | Zero amount | Amount 0 | HTTP 422 |
| TC-04 | Negative amount | Amount -100 | HTTP 422 |
| TC-05 | Invalid card number | Card shorter than 16 digits | HTTP 422 |
| TC-06 | Missing request key | No Idempotency-Key header | HTTP 400 |
| TC-07 | Duplicate request | Same body and key twice | Original payment returned; one row only |
| TC-08 | Reused key with changed request | Same key with different amount | HTTP 409 |
| TC-09 | Retrieve existing payment | Existing payment ID | HTTP 200 and correct details |
| TC-10 | Retrieve unknown payment | Unknown payment ID | HTTP 404 |
| TC-11 | Verify database record | Query payment by ID | Stored amount/status match API response |

Run `pytest` from the project root. Each test uses its own temporary database.
