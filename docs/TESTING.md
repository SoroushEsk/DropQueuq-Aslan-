# DropQueue Testing Plan

The test suite is part of the feature. A reservation endpoint is incomplete if it only passes an HTTP happy-path test.

## Test layers

### Unit tests

Unit tests must run without PostgreSQL, Redis, or a Celery worker. Keep domain decisions in pure services so these tests are fast and deterministic.

Required unit cases:

- reservation state transitions: active, confirmed, cancelled, and expired
- invalid quantities and per-user limits
- expiration boundary conditions
- idempotency-key comparison and request-body conflicts
- inventory invariant calculations
- retry classification: transient versus permanent errors
- reconciliation classification: missing, duplicate, and mismatched events
- pagination and error-code formatting

Unit tests should not mock the rule being tested. For example, a reservation service test should exercise the state transition logic rather than assert that a mock was called.

### Integration tests

Integration tests run with PostgreSQL and a real broker in Docker. They verify transaction boundaries and delivery behavior that unit tests cannot reproduce.

Required integration cases:

1. Two transactions cannot reserve more stock than exists.
2. Repeating one idempotency key returns one reservation row.
3. Concurrent confirmation and expiration result in exactly one terminal transition.
4. Cancellation returns stock once, even when the request is retried.
5. A confirmed reservation creates one fulfillment job through the outbox.
6. A duplicate outbox delivery does not create a duplicate warehouse job.
7. Completing a fulfillment job transfers stock from `reserved` to `fulfilled` once.
8. A duplicate fulfillment callback does not double-count stock.
9. A failed notification is retried and eventually succeeds.
10. A worker restart does not lose or double-apply a task.
11. Reconciliation detects an intentionally deleted or altered event.
12. API authorization prevents one user from reading another user's reservation.

Use `pytest-django` with transactional database tests. Concurrency tests must use PostgreSQL and separate database connections; a shared Django connection can hide locking bugs.

### Celery tests

`task_always_eager` is useful for small unit tests, but it does not test broker acknowledgement, serialization, visibility timeouts, or worker restarts. Keep two categories:

- eager tests for task decision logic and retry classification
- broker-backed tests for delivery, retry, duplicate delivery, and worker recovery

Every task test should assert both the final state and the number of side effects. A task that finishes successfully but sends two notifications is a failure.

## Concurrency test shape

Use a deliberately oversubscribed inventory. For example, create 10 units and start 100 independent clients at the same time. Assert:

```text
successful reservations = 10
active reservations = 10
available stock = 0
negative stock = 0
```

Repeat the test with the same idempotency key from several clients. The expected number of reservation rows is one.

The test should record the order of accepted commands so a failure can be replayed. Do not assert that a particular thread always wins; assert the database invariants and the recorded serialization order.

## Crash and replay tests

Inject failures at these boundaries:

- after the inventory row is locked
- after the reservation row is written
- after the outbox row is written
- after the broker publish but before the delivery acknowledgement
- after a worker side effect but before task acknowledgement

After each injected failure, restart the component and verify that replay converges to the same inventory and reservation state as a clean run.

## Throughput test request

Run two repeatable load profiles.

### Profile 1: reservation burst

- 10,000 clients
- 1,000 available units
- at least 500 requests/second ramp-up
- two-minute steady-state window
- PostgreSQL plus the real broker in Docker

Pass conditions:

- no over-allocation
- no negative inventory
- invariant holds after the test and after reconciliation
- 5xx rate below 1% for the baseline environment
- p50, p95, p99 latency and throughput are recorded

### Profile 2: worker backlog

- confirm 5,000 reservations quickly
- pause fulfillment workers
- resume workers after a controlled delay
- record maximum queue depth, oldest task age, drain time, retries, and duplicate side effects

The report must include:

- commit identifier
- machine and container limits
- database and broker versions
- client concurrency and arrival rate
- dataset size
- throughput, latency, error rate, and resource usage
- any invariant or reconciliation failures

Do not claim that a test is "high throughput" without publishing these numbers.

## Test commands

The exact commands can change with the chosen runner, but the project should expose equivalents to:

```bash
pytest -m unit
pytest -m integration
pytest -m concurrency
locust -f tests/load/locustfile.py --headless -u 10000 -r 500 --run-time 2m
```

Integration and load tests must be isolated from personal data and must target only the local Docker environment.

