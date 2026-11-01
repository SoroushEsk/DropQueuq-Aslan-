import csv
import time
import psutil
import psycopg2

from pathlib import Path
from datetime import datetime
from decouple import config


# =========================
# Configuration
# =========================

DB_NAME = config("DB_NAME")
DB_USER = config("DB_USER")
DB_PASSWORD = config("DB_PASSWORD")
DB_HOST = config("DB_HOST", default="localhost")
DB_PORT = config("DB_PORT", default="5432")

PRODUCT_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
INTERVAL_SECONDS = 2

CPU_COUNT = psutil.cpu_count(logical=True) or 1


# =========================
# Output
# =========================

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_FILE = RESULTS_DIR / f"monitor_{timestamp}.csv"


# =========================
# Database Queries
# =========================

ACTIVITY_QUERY = """
SELECT
    COUNT(*) AS total_connections,
    COUNT(*) FILTER (WHERE state = 'active') AS active_connections,
    COUNT(*) FILTER (WHERE state = 'idle') AS idle_connections,
    COUNT(*) FILTER (
        WHERE wait_event_type = 'Lock'
    ) AS waiting_for_lock
FROM pg_stat_activity
WHERE datname = current_database();
"""

BLOCKING_QUERY = """
SELECT COUNT(*)
FROM pg_stat_activity
WHERE cardinality(pg_blocking_pids(pid)) > 0
AND datname = current_database();
"""

LOCK_WAIT_QUERY = """
SELECT COALESCE(
    MAX(EXTRACT(EPOCH FROM (now() - query_start))),
    0
)
FROM pg_stat_activity
WHERE wait_event_type = 'Lock'
AND datname = current_database();
"""

INVENTORY_QUERY = """
SELECT
    COALESCE(SUM(on_hand), 0),
    COALESCE(SUM(available), 0),
    COALESCE(SUM(reserved), 0),
    COALESCE(SUM(fulfilled), 0)
FROM inventory_inventory
WHERE product_id_id = ANY(%s);
"""

RESERVATION_QUERY = """
SELECT COUNT(*)
FROM reservations_reservation
WHERE product_id_id = ANY(%s);
"""


# =========================
# Process Monitoring
# =========================

# Keep Process objects between samples.
# Otherwise, process.cpu_percent() would always return 0
# on the first measurement.

process_cache = {}


def classify_process(name, cmdline):

    name = name.lower()
    cmdline = cmdline.lower()

    if name in ("postgres.exe", "postgres"):
        return "postgres"

    if "manage.py" in cmdline and "runserver" in cmdline:
        return "django"

    if "locust" in cmdline:
        return "locust"

    return None


def collect_process_metrics():

    metrics = {
        "django_cpu_percent": 0,
        "django_ram_mb": 0,
        "django_pids": [],

        "locust_cpu_percent": 0,
        "locust_ram_mb": 0,
        "locust_pids": [],

        "postgres_cpu_percent": 0,
        "postgres_ram_mb": 0,
        "postgres_pids": [],
    }

    active_pids = set()

    for process in psutil.process_iter(
        ["pid", "name", "cmdline"]
    ):

        try:
            pid = process.info["pid"]
            name = process.info["name"] or ""
            cmdline = " ".join(
                process.info["cmdline"] or []
            )

            category = classify_process(name, cmdline)

            if category is None:
                continue

            active_pids.add(pid)

            # Reuse Process object for CPU measurement
            if pid not in process_cache:
                process_cache[pid] = psutil.Process(pid)

            proc = process_cache[pid]

            # Normalize CPU usage against total logical CPUs.
            # Example: 100% of one core on an 8-core machine = 12.5%.
            cpu_percent = proc.cpu_percent(interval=None) / CPU_COUNT

            memory_mb = (
                proc.memory_info().rss / (1024 * 1024)
            )

            metrics[f"{category}_cpu_percent"] += cpu_percent
            metrics[f"{category}_ram_mb"] += memory_mb
            metrics[f"{category}_pids"].append(str(pid))

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess
        ):
            continue

    # Remove terminated processes from cache
    for pid in list(process_cache.keys()):
        if pid not in active_pids:
            process_cache.pop(pid, None)

    for category in ("django", "locust", "postgres"):
        metrics[f"{category}_pids"] = ",".join(
            metrics[f"{category}_pids"]
        )

    return metrics


# =========================
# Collect Metrics
# =========================

def collect_metrics(cursor):

    metrics = {}

    # System CPU and RAM
    metrics["system_cpu_percent"] = psutil.cpu_percent(
        interval=None
    )

    metrics["system_ram_percent"] = psutil.virtual_memory().percent

    metrics["system_ram_used_mb"] = (
        psutil.virtual_memory().used / (1024 * 1024)
    )

    # Individual processes
    metrics.update(collect_process_metrics())

    # PostgreSQL connections
    cursor.execute(ACTIVITY_QUERY)

    row = cursor.fetchone()

    metrics["db_total_connections"] = row[0]
    metrics["db_active_connections"] = row[1]
    metrics["db_idle_connections"] = row[2]
    metrics["db_waiting_for_lock"] = row[3]

    # Blocked processes
    cursor.execute(BLOCKING_QUERY)

    metrics["db_blocked_processes"] = cursor.fetchone()[0]

    # Maximum age of queries currently waiting for locks.
    # This is NOT the exact lock-wait duration.
    cursor.execute(LOCK_WAIT_QUERY)

    metrics["max_lock_query_age_seconds"] = float(
        cursor.fetchone()[0]
    )

    # Inventory state
    cursor.execute(INVENTORY_QUERY, (PRODUCT_IDS,))

    inventory = cursor.fetchone()

    if inventory:
        metrics["inventory_on_hand"] = inventory[0]
        metrics["inventory_available"] = inventory[1]
        metrics["inventory_reserved"] = inventory[2]
        metrics["inventory_fulfilled"] = inventory[3]
    else:
        metrics["inventory_on_hand"] = 0
        metrics["inventory_available"] = 0
        metrics["inventory_reserved"] = 0
        metrics["inventory_fulfilled"] = 0

    # Reservation count
    cursor.execute(RESERVATION_QUERY, (PRODUCT_IDS,))

    metrics["reservation_count"] = cursor.fetchone()[0]

    return metrics


# =========================
# CSV Fields
# =========================

FIELDNAMES = [
    "timestamp",

    "system_cpu_percent",
    "system_ram_percent",
    "system_ram_used_mb",

    "django_cpu_percent",
    "django_ram_mb",
    "django_pids",

    "locust_cpu_percent",
    "locust_ram_mb",
    "locust_pids",

    "postgres_cpu_percent",
    "postgres_ram_mb",
    "postgres_pids",

    "db_total_connections",
    "db_active_connections",
    "db_idle_connections",
    "db_waiting_for_lock",
    "db_blocked_processes",
    "max_lock_query_age_seconds",

    "inventory_on_hand",
    "inventory_available",
    "inventory_reserved",
    "inventory_fulfilled",

    "reservation_count",
]


# =========================
# Main
# =========================

def main():

    print("Connecting to PostgreSQL...")

    connection = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )

    connection.autocommit = True
    cursor = connection.cursor()

    # Prime CPU counters before the first real sample
    psutil.cpu_percent(interval=None)

    print("Monitoring started.")
    print(f"CSV output: {CSV_FILE}")
    print(f"Sampling interval: {INTERVAL_SECONDS} seconds")
    print("Press CTRL+C to stop.\n")

    try:

        with open(
            CSV_FILE,
            mode="w",
            newline="",
            encoding="utf-8"
        ) as csv_file:

            writer = csv.DictWriter(
                csv_file,
                fieldnames=FIELDNAMES
            )

            writer.writeheader()

            while True:

                metrics = collect_metrics(cursor)

                metrics["timestamp"] = datetime.now().isoformat(
                    timespec="seconds"
                )

                writer.writerow(metrics)
                csv_file.flush()

                print(
                    f"[{metrics['timestamp']}] "
                    f"CPU: {metrics['system_cpu_percent']:.1f}% | "
                    f"Django: {metrics['django_cpu_percent']:.1f}% | "
                    f"Locust: {metrics['locust_cpu_percent']:.1f}% | "
                    f"Postgres: {metrics['postgres_cpu_percent']:.1f}% | "
                    f"Locks: {metrics['db_waiting_for_lock']} | "
                    f"Blocked: {metrics['db_blocked_processes']} | "
                    f"DB Active: {metrics['db_active_connections']}"
                )

                time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:

        print("\nMonitoring stopped.")

    finally:

        cursor.close()
        connection.close()

        print(f"Results saved to: {CSV_FILE}")


if __name__ == "__main__":
    main()