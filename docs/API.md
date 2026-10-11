# DropQueue API

## Purpose

DropQueue is a high-throughput inventory reservation and warehouse fulfillment service. A product drop may have a small amount of stock and a large burst of users trying to reserve it at the same time.

This is an educational system. It does not process real money, trading orders, banking data, or cryptocurrency. Its purpose is to exercise the same backend engineering problems found in high-volume systems: concurrency, idempotency, durable events, retries, recovery, and measurable throughput.

The contract below is the implementation target. An endpoint is not considered complete until its unit and integration tests described in [TESTING.md](TESTING.md) pass.

## Service boundaries

The first version may run as one Django application, but these responsibilities must remain separate:

- **Catalog:** products, drops, and published stock limits.
- **Reservation:** atomic stock allocation, expiration, cancellation, and confirmation.
- **Fulfillment:** warehouse work created after confirmation.
- **Outbox:** durable domain events produced in the same transaction as state changes.
- **Workers:** Celery tasks for expiration, notifications, fulfillment, and reconciliation.

PostgreSQL is the source of truth for inventory. Redis is a broker/cache, not the authoritative inventory store.

## Conventions

- Base URL: `/api/v1`
- Content type: `application/json`
- IDs: opaque UUID strings; clients must not depend on their format.
- Timestamps: ISO-8601 UTC, for example `2026-10-11T12:30:00Z`.
- Quantities: positive integers. Fractional stock is not supported.
- Authentication: bearer token in production; development may use a test user.
- Every mutating request accepts an `Idempotency-Key` header.
- A reused key with a different request body returns `409 Conflict`.
- A successful reservation response is `201 Created`.
- A request that is accepted for asynchronous processing returns `202 Accepted` and a task reference.

### Error format

All errors use the same shape:

```json
{
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "The requested quantity is not available.",
    "request_id": "req_01J...",
    "details": {}
  }
}
```

Clients should branch on `error.code`, not on the human-readable message.

## Resource states

### Reservation

```text
ACTIVE -> CONFIRMED
ACTIVE -> CANCELLED
ACTIVE -> EXPIRED
CONFIRMED -> FULFILLED
```

`CANCELLED`, `EXPIRED`, and `FULFILLED` are terminal states. A terminal reservation cannot be changed by a retry. `CONFIRMED` remains active until the warehouse reports fulfillment.

### Inventory invariant

For every SKU, the following must always hold:

```text
on_hand = available + reserved + fulfilled
available >= 0
reserved >= 0
fulfilled >= 0
```

## Endpoints

### Create a product drop

`POST /api/v1/drops`

Creates a product drop and its initial inventory. This is an administrative endpoint.

Request:

```json
{
  "name": "Limited Canvas Backpack",
  "sku": "BAG-CANVAS-001",
  "on_hand": 1000,
  "reservation_ttl_seconds": 120,
  "starts_at": "2026-10-12T09:00:00Z"
}
```

Response `201 Created`:

```json
{
  "id": "drop_7a4d...",
  "name": "Limited Canvas Backpack",
  "sku": "BAG-CANVAS-001",
  "status": "SCHEDULED",
  "reservation_ttl_seconds": 120,
  "inventory": {
    "on_hand": 1000,
    "available": 1000,
    "reserved": 0,
    "fulfilled": 0
  },
  "starts_at": "2026-10-12T09:00:00Z",
  "created_at": "2026-10-11T12:30:00Z"
}
```

Validation:

- `on_hand` must be greater than zero.
- `reservation_ttl_seconds` must be between 30 and 1800.
- `sku` is unique.
- `starts_at` must be in the future when the drop is scheduled.

### List drops

`GET /api/v1/drops?status=LIVE&cursor=<cursor>&limit=50`

Returns a cursor-paginated list. `limit` is capped at 100.

Response `200 OK`:

```json
{
  "results": [
    {
      "id": "drop_7a4d...",
      "name": "Limited Canvas Backpack",
      "sku": "BAG-CANVAS-001",
      "status": "LIVE",
      "starts_at": "2026-10-12T09:00:00Z"
    }
  ],
  "next_cursor": null
}
```

### Get drop availability

`GET /api/v1/drops/{drop_id}/availability`

Returns a read model for display. It is not a reservation and may become stale immediately under load.

Response `200 OK`:

```json
{
  "drop_id": "drop_7a4d...",
  "sku": "BAG-CANVAS-001",
  "status": "LIVE",
  "available": 37,
  "as_of": "2026-10-12T09:01:14Z"
}
```

### Create a reservation

`POST /api/v1/drops/{drop_id}/reservations`

Atomically reserves stock for the authenticated user. The critical inventory update must happen inside a PostgreSQL transaction with a row lock or an equivalent optimistic-concurrency guarantee.

Headers:

```text
Idempotency-Key: reserve-user-123-drop-7a4d
```

Request:

```json
{
  "quantity": 2,
  "client_request_id": "client-req-0001"
}
```

Response `201 Created`:

```json
{
  "id": "reservation_91bf...",
  "drop_id": "drop_7a4d...",
  "user_id": "user_123",
  "quantity": 2,
  "status": "ACTIVE",
  "expires_at": "2026-10-12T09:03:14Z",
  "created_at": "2026-10-12T09:01:14Z"
}
```

Possible errors:

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `INVALID_QUANTITY` | Quantity is zero, negative, or above the per-user limit. |
| 409 | `DROP_NOT_LIVE` | The drop is not accepting reservations. |
| 409 | `INSUFFICIENT_STOCK` | The requested quantity is not available. |
| 409 | `IDEMPOTENCY_CONFLICT` | The key was used with a different request body. |
| 429 | `RATE_LIMITED` | The caller exceeded the reservation rate limit. |

Example request:

```bash
curl -X POST http://localhost:8000/api/v1/drops/drop_7a4d.../reservations \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: reserve-user-123-drop-7a4d' \
  -d '{"quantity": 2, "client_request_id": "client-req-0001"}'
```

### Confirm a reservation

`POST /api/v1/reservations/{reservation_id}/confirm`

Moves an active reservation to `CONFIRMED` and creates a fulfillment job through the outbox. No payment is performed.

Headers:

```text
Idempotency-Key: confirm-reservation-91bf
```

Response `200 OK`:

```json
{
  "id": "reservation_91bf...",
  "status": "CONFIRMED",
  "fulfillment_job_id": "job_44ce...",
  "confirmed_at": "2026-10-12T09:02:00Z"
}
```

Confirming an already confirmed reservation returns the same representation. Confirming an expired or cancelled reservation returns `409`.

### Cancel a reservation

`POST /api/v1/reservations/{reservation_id}/cancel`

Returns active stock to `available` and moves the reservation to `CANCELLED`.

Response `200 OK`:

```json
{
  "id": "reservation_91bf...",
  "status": "CANCELLED",
  "cancelled_at": "2026-10-12T09:02:30Z"
}
```

Cancellation must be serialized against confirmation and expiration. Exactly one terminal transition wins.

### Get a reservation

`GET /api/v1/reservations/{reservation_id}`

Returns the current state and audit timestamps. A user may read only their own reservations unless they have an administrative role.

### List a user's reservations

`GET /api/v1/reservations?status=ACTIVE&cursor=<cursor>&limit=50`

Results are cursor-paginated and scoped to the authenticated user.

### Get a fulfillment job

`GET /api/v1/fulfillment/jobs/{job_id}`

Response `200 OK`:

```json
{
  "id": "job_44ce...",
  "reservation_id": "reservation_91bf...",
  "status": "QUEUED",
  "attempts": 0,
  "last_error": null,
  "created_at": "2026-10-12T09:02:00Z",
  "updated_at": "2026-10-12T09:02:00Z"
}
```

### Complete a fulfillment job

`POST /api/v1/fulfillment/jobs/{job_id}/complete`

This internal warehouse callback moves the job to `COMPLETED`, moves the reservation to `FULFILLED`, and transfers the quantity from `reserved` to `fulfilled` in one transaction. It is idempotent: repeating the callback must not increment `fulfilled` twice.

Headers:

```text
Idempotency-Key: warehouse-complete-job-44ce
```

Response `200 OK`:

```json
{
  "id": "job_44ce...",
  "status": "COMPLETED",
  "reservation_id": "reservation_91bf...",
  "completed_at": "2026-10-12T09:10:00Z"
}
```

### Health and metrics

`GET /health/live`

Returns `200` when the web process is alive. It must not query every dependency.

`GET /health/ready`

Returns `200` only when PostgreSQL and the task broker are usable. It returns `503` otherwise.

`GET /metrics`

Exposes Prometheus-compatible metrics, including request count, request latency, reservation conflicts, task retries, queue depth, and reconciliation mismatches.

## Background task contracts

Celery tasks use at-least-once delivery. Every task must be safe to retry.

| Task | Trigger | Required behavior |
| --- | --- | --- |
| `expire_reservation(reservation_id)` | ETA at `expires_at` | Lock the reservation, transition only if still `ACTIVE`, and return stock exactly once. |
| `dispatch_fulfillment(reservation_id)` | `ReservationConfirmed` event | Create or reuse one warehouse job. Duplicate events must not create duplicate jobs. |
| `send_reservation_notification(reservation_id)` | Reservation event | Use a notification idempotency key; retry transient failures with backoff. |
| `relay_outbox_event(event_id)` | Outbox poller | Publish an event, record delivery, and tolerate duplicate delivery. |
| `reconcile_inventory(drop_id)` | Periodic schedule | Compare the inventory aggregate with reservations and report mismatches without guessing a correction. |

The API transaction must not wait for email, warehouse integration, or other network calls. State changes are committed first; workers process outbox events afterward.

## Throughput test request

The performance test must model a burst, not a quiet sequential benchmark.

### Scenario A: oversubscribed drop

- Inventory: 1,000 units.
- Concurrent clients: 10,000.
- Each client sends one reservation request.
- Ramp rate: at least 500 requests per second until the target concurrency is reached.
- Duration: 2 minutes after warm-up.
- Run against PostgreSQL and Redis/RabbitMQ in Docker, not SQLite and eager Celery mode.

Acceptance criteria for the baseline environment:

- Successful reservations never exceed 1,000.
- `available` never becomes negative.
- Inventory invariant remains true after the run.
- Duplicate idempotency keys create one reservation only.
- HTTP 5xx rate is below 1%.
- Record throughput and p50, p95, and p99 latency; publish the measured baseline rather than inventing a universal target.

### Scenario B: worker backlog

- Confirm 5,000 reservations in a short burst.
- Delay the fulfillment worker and observe queue depth.
- Restore workers and measure drain time, retry count, and duplicate-job count.
- Verify that API reservation latency is not coupled to fulfillment latency.

Example load request body:

```json
{
  "quantity": 1,
  "client_request_id": "load-test-{{ unique_client_id }}"
}
```

The load generator must create a unique `Idempotency-Key` per logical client, then repeat a subset of keys to verify duplicate-request behavior.

### Required measurements

- requests per second
- p50/p95/p99 API latency
- database lock wait time
- reservation conflict rate
- queue depth and task age
- task retry and failure counts
- database CPU, connections, and transaction duration
- memory and CPU for web and worker processes
- reconciliation mismatches after the run

The load test must be repeatable with a fixed seed and must leave a report containing the git commit, configuration, dataset size, and measured results.

## Compatibility and versioning

Breaking changes require a new `/api/v2` prefix. Adding response fields is backward-compatible. Clients must ignore unknown response fields and use error codes for control flow.

