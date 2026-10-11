# DropQueue: The Day 10,000 People Wanted 1,000 Backpacks

## Start with the story

Imagine a small company called **Northwind Goods**. On Friday morning it releases 1,000 limited-edition backpacks.

The company expects many visitors, so it builds DropQueue. DropQueue does not handle real money. Its only job is to make sure that:

- a backpack is never promised to two people
- a request can be safely repeated
- temporary reservations expire
- warehouse work continues even when a worker crashes
- the company can prove that its inventory is still correct

The system is interesting because 10,000 people may click the button at almost the same moment.

## The characters

It is easier to understand the architecture if each part has a job:

- **Maya, the customer:** clicks "Reserve" from her browser.
- **The API receptionist:** receives requests and checks their shape.
- **PostgreSQL, the stock notebook:** stores the official inventory numbers.
- **The outbox, the dispatch tray:** records what happened before another system is told.
- **Celery workers, the assistants:** expire reservations, send notifications, and create warehouse jobs.
- **The warehouse:** picks and packs a confirmed reservation.
- **The reconciliation worker, the auditor:** checks that all records still agree.

At the beginning, these parts may live in one Django repository. They are separated by responsibility so that the design can grow later.

## Chapter 1: Before the doors open

An administrator creates a drop:

~~~
Product: Limited Canvas Backpack
Stock: 1,000
Reservation time: 2 minutes
Status: SCHEDULED
~~~

The inventory starts like this:

~~~
on_hand   = 1,000
available = 1,000
reserved  = 0
fulfilled = 0
~~~

The important rule is:

~~~
on_hand = available + reserved + fulfilled
~~~

This rule is the system's promise. Every feature and every test must protect it.

## Chapter 2: The doors open

At 09:00 the drop becomes live. Ten thousand clients send reservation requests.

Maya's request reaches the API:

~~~
POST /api/v1/drops/drop-123/reservations
Idempotency-Key: maya-drop-123
~~~

The API does not simply read the available count and then write a new number. That would allow two requests to read the same old value and sell the same backpack twice.

Instead, one database transaction does all of the following:

1. Lock the inventory row.
2. Check that enough stock is available.
3. Create Maya's reservation.
4. Decrease the available count.
5. Increase the reserved count.
6. Write an outbox event saying ReservationCreated.
7. Commit the transaction.

For two backpacks, the numbers become:

~~~
on_hand   = 1,000
available = 998
reserved  = 2
fulfilled = 0
~~~

Only after the transaction commits can the API return success.

The first 1,000 valid units win. Other clients receive INSUFFICIENT_STOCK. They may see a busy service, but they must never see negative stock or a reservation for an unavailable item.

## Chapter 3: Maya clicks twice

Maya's Wi-Fi is slow. She does not know whether the first request succeeded, so her browser sends the request again with the same Idempotency-Key.

DropQueue looks up the key and returns the original reservation. It does not create a second reservation or subtract stock again.

If Maya reuses the same key with a different quantity, the API returns IDEMPOTENCY_CONFLICT. A key identifies one logical operation, not an unlimited number of different requests.

This is why idempotency matters: clients, proxies, and workers can retry without turning one action into two actions.

## Chapter 4: The two-minute hold

Maya has two minutes to confirm her reservation. The API has already returned, so it does not keep a web request open while waiting.

Instead, Celery schedules:

~~~
expire_reservation(reservation_id=...)
~~~

When the task runs, it locks the reservation and checks its current state:

- If it is still ACTIVE and the deadline passed, change it to EXPIRED and return stock.
- If Maya already confirmed it, do nothing.
- If the task is delivered twice, the second delivery does nothing.

The task is safe to retry. Celery provides at-least-once delivery, which means a task can run more than once after a timeout or worker failure.

## Chapter 5: Maya confirms

Maya confirms before the deadline:

~~~
POST /api/v1/reservations/reservation-456/confirm
Idempotency-Key: confirm-reservation-456
~~~

The API changes the reservation from ACTIVE to CONFIRMED and writes a ReservationConfirmed outbox event.

The API transaction does not call the warehouse, send email, or wait for another network service. Those actions happen after commit. Keeping the transaction short makes it easier for many requests to proceed.

An outbox worker reads the event and creates one warehouse job:

~~~
ReservationConfirmed
        |
        v
Fulfillment job QUEUED
~~~

If the event is delivered twice, a unique reservation or event key makes the second delivery harmless.

## Chapter 6: The warehouse worker crashes

The warehouse worker receives the job, prints a picking label, and crashes before acknowledging the task.

The broker delivers the task again. This is not an exceptional design flaw; it is a normal distributed-systems situation.

The worker must ask:

~~~
Has this fulfillment job already been completed?
~~~

If yes, it returns the existing result. If no, it performs the work and records the completion atomically.

When the backpack is finally fulfilled, the inventory changes:

~~~
on_hand   = 1,000
available = 998
reserved  = 0
fulfilled = 2
~~~

The same inventory invariant still holds.

## Chapter 7: The auditor checks the books

Every hour, the reconciliation worker compares:

- inventory totals
- reservation states
- fulfillment jobs
- outbox events

It may discover that an event is delayed, duplicated, missing, or has the wrong quantity.

The auditor reports the difference. It does not silently guess a correction. A real correction must be based on a known source of truth and leave an audit trail.

This gives the project an important production habit: detecting an inconsistency is different from pretending it never happened.

## Why this becomes difficult

The business rule sounds simple: "do not sell more backpacks than exist." The engineering problems appear when many things happen together:

- thousands of requests compete for one inventory row
- a client repeats a request after a timeout
- a reservation expires while confirmation is being processed
- a worker succeeds but loses its acknowledgement
- a message arrives twice
- a read-only availability page is already stale
- a database transaction commits while a downstream service is unavailable
- a queue grows faster than workers can drain it

DropQueue is a safe way to practice these problems without handling money or financial accounts.

## How the tests fit the story

### Unit test: one character at a time

Test the rules without a database or broker:

- an active reservation can be confirmed
- an expired reservation cannot be confirmed
- an invalid quantity is rejected
- a repeated task does not apply its side effect twice
- inventory arithmetic preserves the invariant

These tests are fast and explain the domain rules.

### Integration test: the real workplace

Run Django with PostgreSQL and a real broker in Docker:

- two transactions compete for the last unit
- only one wins
- an outbox event creates one fulfillment job
- a duplicate event does not create a second job
- a worker restart does not lose the task

These tests reveal problems that mocks and SQLite can hide.

### Concurrency test: the crowded doorway

Create 10 units and start 100 independent clients at once. The expected result is:

~~~
successful reservations = 10
active reservations      = 10
available stock          = 0
negative stock           = 0
~~~

Do not require a particular thread to win. Require the invariant and the recorded ordering to be correct.

### Throughput test: the launch event

Run the story at a larger scale:

- 10,000 clients
- 1,000 units
- at least 500 requests per second during ramp-up
- PostgreSQL and a real broker

Measure requests per second, p50/p95/p99 latency, database lock waits, queue depth, retries, error rate, and reconciliation results. A throughput claim is meaningful only when these numbers are recorded with the machine and configuration.

## A simple implementation path

Build the story in this order:

1. Implement inventory and reservation rules in plain Python.
2. Add Django models and PostgreSQL transactions.
3. Add the reservation, confirmation, cancellation, and availability APIs.
4. Add idempotency keys and the outbox table.
5. Add Celery expiration and fulfillment workers.
6. Add integration and concurrency tests.
7. Add crash injection, reconciliation, and load tests.
8. Add metrics and document the measured baseline.

Do not begin with Kafka, Kubernetes, or many microservices. First make Maya's one reservation correct. Then make 10,000 reservations safe.

## Small glossary

- **Reservation:** a temporary promise of stock to one user.
- **Idempotency:** repeating one logical request has the same effect as sending it once.
- **Outbox:** a durable record of an event written with the business change.
- **At-least-once delivery:** a worker may receive the same task more than once.
- **Reconciliation:** comparing independent records to find disagreement.
- **Throughput:** how many requests the system completes per unit of time.
- **p95/p99 latency:** the response time below which 95% or 99% of requests finish.

