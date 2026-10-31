"""Concurrent reservation tests will be added later."""
import uuid
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
            on_hand=10,
            available=10,
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
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )

            return response.status_code, response.data

        finally:
            close_old_connections()

    def test_only_one_request_succeeds_for_last_unit(self):
        number_of_requests = 20
        self.inventory.available = 1
        self.inventory.on_hand = 1
        self.inventory.save(update_fields=["available", "on_hand"])
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

            # status_codes = [
            #     future.result()
            #     for future in futures
            # ]
            results = [
                future.result()
                for future in futures
            ]

            # print("Results:", results)

            status_codes = [
                status_code
                for status_code, _ in results
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

    def test_concurrent_requests_with_same_key_create_one_reservation(self):
        idempotency_key = str(uuid.uuid4())
        request_count = 100

        def send_request(_):
            close_old_connections()
            try:
                client = APIClient()
                return client.post(
                    self.url,
                    {"product_id": self.product.product_id},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=idempotency_key,
                ).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=10) as executor:
            statuses = list(executor.map(send_request, range(request_count)))

        self.assertEqual(statuses.count(201), request_count)
        self.assertEqual(Reservation.objects.count(), 1)

        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.available, 9)
        self.assertEqual(self.inventory.reserved, 1)
        
        
    def test_concurrent_requests_with_different_keys_respect_stock(self):
        request_count = 100

        def send_request(_):
            close_old_connections()
            try:
                client = APIClient()
                return client.post(
                    self.url,
                    {"product_id": self.product.product_id},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                ).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=10) as executor:
            statuses = list(executor.map(send_request, range(request_count)))

        self.assertEqual(statuses.count(201), 10)
        self.assertEqual(statuses.count(400), 90)
        self.assertEqual(Reservation.objects.count(), 10)

        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.available, 0)
        self.assertEqual(self.inventory.reserved, 10)
        
        
    def test_same_key_concurrently_for_different_products(self):
        second_product = Product.objects.create(name="Second product")

        second_inventory = Inventory.objects.create(
            product_id=second_product,
            on_hand=10,
            available=10,
            reserved=0,
            fulfilled=0,
        )

        idempotency_key = str(uuid.uuid4())
        barrier = Barrier(2)

        def send_request(product_id):
            close_old_connections()
            try:
                barrier.wait()
                client = APIClient()
                response = client.post(
                    self.url,
                    {"product_id": product_id},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=idempotency_key,
                )
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    send_request,
                    self.product.product_id,
                ),
                executor.submit(
                    send_request,
                    second_product.product_id,
                ),
            ]
            status_codes = [future.result() for future in futures]

        self.assertEqual(status_codes.count(201), 1)
        self.assertEqual(status_codes.count(409), 1)
        self.assertEqual(Reservation.objects.count(), 1)

        self.inventory.refresh_from_db()
        second_inventory.refresh_from_db()

        self.assertEqual(
            self.inventory.available + second_inventory.available,
            19,
        )