# DropQueue

DropQueue is a blank Django foundation for a high-throughput inventory reservation and warehouse fulfillment project.

The project uses a non-financial domain to practice concurrency, idempotency, PostgreSQL transactions, Celery jobs, retries, outbox events, reconciliation, and throughput testing.

## Documentation

- [Development guide and commands](DEVELOPMENT.md)
- [Project story](docs/PROJECT_STORY.md)
- [API contract](docs/API.md)
- [Testing plan](docs/TESTING.md)

## Django apps

- **catalog:** products and product drops
- **inventory:** stock and inventory invariants
- **reservations:** temporary stock reservations
- **fulfillment:** warehouse jobs
- **outbox:** durable events and reconciliation

The apps are intentionally empty. Add models, endpoints, tasks, and tests in small steps while following the documentation.

## Local setup

~~~bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py check
python manage.py runserver
~~~

Redis and PostgreSQL are optional for the initial blank scaffold. They become required when Celery and integration tests are implemented.
