"""Load-test scenarios will be added after the API is implemented."""

import uuid, random

from locust import HttpUser, task, between
PRODUCT_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

class ReservationUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def create_reservation(self):
        idempotency_key = str(uuid.uuid4())
        product_id = random.choice(PRODUCT_IDS)
        self.client.post(
            "/api/v1/reservations/",
            json={"product_id": product_id},
            headers={"Idempotency-Key": idempotency_key},
            name="/api/v1/reservations/ [POST]",
        )
