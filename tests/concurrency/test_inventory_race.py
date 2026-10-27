"""Concurrent reservation tests will be added later."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from catalog.models import Product
from inventory.models import Inventory
from reservations.models import Reservation


class InventoryRaceTests(TransactionTestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Race Test Product",
            reservation_expiring_time_by_min=2,
        )

        self.inventory = Inventory.objects.create(
            product_id=self.product,
            on_hand=1,
            available=1,
            reserved=0,
            fulfilled=0,
        )

        self.url = "/api/v1/reservations/"

    def make_reservation_request(self, barrier):
        close_old_connections()

        try:
            client = APIClient()

            # همه threadها تا رسیدن بقیه منتظر می‌مانند.
            barrier.wait(timeout=15)

            response = client.post(
                self.url,
                {"product_id": self.product.product_id},
                format="json",
            )

            return response.status_code

        finally:
            close_old_connections()

    def test_only_one_request_succeeds_for_last_unit(self):
        number_of_requests = 20
        barrier = Barrier(number_of_requests)

        with ThreadPoolExecutor(
            max_workers=number_of_requests
        ) as executor:
            futures = [
                executor.submit(
                    self.make_reservation_request,
                    barrier,
                )
                for _ in range(number_of_requests)
            ]

            status_codes = [
                future.result()
                for future in futures
            ]

        self.assertEqual(status_codes.count(201), 1)
        self.assertEqual(status_codes.count(400), 19)

        self.inventory.refresh_from_db()

        self.assertEqual(self.inventory.available, 0)
        self.assertEqual(self.inventory.reserved, 1)

        self.assertEqual(
            Reservation.objects.filter(
                product_id=self.product
            ).count(),
            1,
        )
