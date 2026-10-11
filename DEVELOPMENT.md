# DropQueue Development Guide

## What this project is

DropQueue is a blank Django project for a high-throughput inventory reservation system.

Imagine a store releasing 1,000 limited-edition backpacks. Thousands of people may try to reserve them at the same time. The project will eventually make sure that:

- stock is never allocated twice
- repeated requests are safe
- reservations expire automatically
- warehouse work runs in Celery
- failed tasks can be retried
- the inventory can be checked after a failure
- the system can be measured under load

The project does not process real money or financial transactions.

The current repository is deliberately a scaffold. The apps, URLs, models, API views, and tasks are empty so they can be implemented step by step.

## Project layout

~~~text
DropQueue/
|-- manage.py
|-- dropqueue/
|   |-- settings.py       Django settings
|   |-- urls.py           top-level URL routing
|   |-- celery.py         Celery application
|   |-- asgi.py           ASGI entry point
|   +-- wsgi.py           WSGI entry point
|-- catalog/              products and product drops
|-- inventory/            stock and inventory rules
|-- reservations/         temporary stock reservations
|-- fulfillment/          warehouse jobs
|-- outbox/               durable events and reconciliation
|-- tests/
|   |-- unit/
|   |-- integration/
|   |-- concurrency/
|   +-- load/
|-- docs/
|   |-- PROJECT_STORY.md  beginner explanation
|   |-- API.md            API contract
|   +-- TESTING.md        testing requirements
|-- requirements.txt      runtime packages
|-- requirements-dev.txt  development and load-test packages
|-- .env.example          local configuration template
+-- .gitignore            ignored local files
~~~

## First-time setup

Run these commands from the project root:

~~~bash
cd ~/PycharmProjects/DropQueue
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py check
python manage.py migrate
~~~

On Windows PowerShell, activate the environment with:

~~~powershell
.\.venv\Scripts\Activate.ps1
~~~

The local scaffold uses SQLite by default. PostgreSQL and Redis become necessary when transaction concurrency and Celery integration are implemented.

## Daily Django commands

Check the project:

~~~bash
python manage.py check
~~~

Start the development server:

~~~bash
python manage.py runserver
~~~

Run the server on another port:

~~~bash
python manage.py runserver 0.0.0.0:8000
~~~

Create database tables:

~~~bash
python manage.py migrate
~~~

Create migrations after adding or changing models:

~~~bash
python manage.py makemigrations
python manage.py migrate
~~~

Show migration status:

~~~bash
python manage.py showmigrations
~~~

Create an administrator:

~~~bash
python manage.py createsuperuser
~~~

Open an interactive Django shell:

~~~bash
python manage.py shell
~~~

Create another Django app in the future:

~~~bash
python manage.py startapp app_name
~~~

The five DropQueue apps already exist. Do not create them again.

## URL namespaces

The blank project reserves these API prefixes:

~~~text
/api/v1/catalog/
/api/v1/inventory/
/api/v1/reservations/
/api/v1/fulfillment/
~~~

They currently contain no endpoints. Add an endpoint to the responsible app's urls.py, then include its view and serializer there.

## Celery and Redis commands

Start Redis locally before starting a worker. The default Redis URL is:

~~~text
redis://localhost:6379/0
~~~

Start a Celery worker:

~~~bash
celery -A dropqueue worker --loglevel=INFO
~~~

Start the periodic task scheduler:

~~~bash
celery -A dropqueue beat --loglevel=INFO
~~~

Run both in separate terminals. Celery tasks should be added to the tasks.py file of the app that owns them.

Every task must be safe to run more than once. A worker can receive a task again after a timeout or crash.

## Database configuration

The default local database is SQLite:

~~~text
DATABASE_URL=sqlite:///db.sqlite3
~~~

For PostgreSQL, place a connection URL in .env:

~~~text
DATABASE_URL=postgres://dropqueue_user:dropqueue_password@localhost:5432/dropqueue
~~~

After changing database configuration, run:

~~~bash
python manage.py check
python manage.py migrate
~~~

## Test commands

The test folders are empty placeholders at the moment.

Run Django's built-in test discovery:

~~~bash
python manage.py test
~~~

Run unit tests after pytest tests are implemented:

~~~bash
pytest -m unit
~~~

Run integration tests with PostgreSQL and a real broker:

~~~bash
pytest -m integration
~~~

Run concurrency tests with separate database connections:

~~~bash
pytest -m concurrency
~~~

Do not use SQLite to claim that the concurrency behavior is correct. PostgreSQL row locking is part of the behavior being tested.

## Throughput test commands

After the API and load scenario are implemented, run Locust locally:

~~~bash
locust -f tests/load/locustfile.py --headless -u 10000 -r 500 --run-time 2m
~~~

The throughput report should include:

- requests per second
- p50, p95, and p99 latency
- HTTP error rate
- database lock wait time
- queue depth and task age
- task retries and failures
- CPU, memory, and database connections
- inventory invariant and reconciliation results

The expected reservation scenario is 10,000 clients competing for 1,000 units. Successful reservations must never exceed the available stock.

## Recommended implementation order

1. Add catalog and inventory models.
2. Add the inventory invariant and reservation service.
3. Add PostgreSQL transactions and row locking.
4. Add the reservation API and idempotency keys.
5. Add the outbox model and event relay.
6. Add reservation expiration with Celery.
7. Add confirmation and fulfillment jobs.
8. Add unit, integration, and concurrency tests.
9. Add reconciliation and failure injection.
10. Add the Locust throughput scenario and metrics.

Keep the first implementation small. A correct reservation flow is more useful than many unfinished endpoints.

## Git commands

Initialize Git if this new directory is not already a repository:

~~~bash
git init
git status
~~~

Review the files that will be committed:

~~~bash
git status --short
git diff
~~~

Create the first commit:

~~~bash
git add .
git commit -m "Create blank DropQueue Django scaffold"
~~~

The .gitignore excludes virtual environments, .env files, SQLite data, caches, logs, IDE files, Celery schedules, and test reports.
