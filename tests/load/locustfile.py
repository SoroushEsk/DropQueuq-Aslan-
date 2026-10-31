"""Load-test scenarios will be added after the API is implemented."""

import uuid

from locust import HttpUser, task, between


class ReservationUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def create_reservation(self):
        idempotency_key = str(uuid.uuid4())

        self.client.post(
            "/api/v1/reservations/",
            json={"product_id": 1},
            headers={"Idempotency-Key": idempotency_key},
            name="/api/v1/reservations/ [POST]",
        )
