# Interview Preparation Guide

Describe only features present in this version.

## Explain the project
"It is a simulated payment API with an automated testing framework. I send dummy payment requests, check whether the payment succeeds or fails as expected, and verify that the transaction is saved correctly."

## Why this project?
"Payment is an important part of many applications. I wanted to practise testing successful payments, declined payments, invalid inputs, duplicate requests, and transaction records."

## What does FastAPI do?
"FastAPI creates API endpoints that receive payment requests and return responses."

## What does Pytest do?
"Pytest runs automated test functions and checks whether actual results match expected results."

## Why SQLite?
"SQLite is a lightweight database that stores simulated payment details in a local file."

## What is idempotency?
"Repeating the same request should not create another payment. The client sends an Idempotency-Key. If the same request is repeated with that key, the API returns the original payment."

## How did you test a declined payment?
"I used a dummy card number ending in 0002. The simulator marks the transaction as FAILED, and my test checks the returned status and failure reason."

## How did you verify the database?
"After creating a payment through the API, a test reads the SQLite record and checks that the saved amount and status match the API response."

## Does it process real payments?
"No. It is an educational simulation and is not connected to a bank or real payment gateway."

Do not claim refunds, webhooks, a financial ledger, performance testing, or concurrent-load testing in this version.
