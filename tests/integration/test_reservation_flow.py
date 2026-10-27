"""PostgreSQL and broker integration tests will be added later."""

from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import Product
from inventory.models import Inventory
from reservations.models import Reservation


class ReservationFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.product = Product.objects.create(
            name="Test Product",
            reservation_expiring_time_by_min=2,
        )

        self.inventory = Inventory.objects.create(
            product_id=self.product,
            on_hand=3,
            available=3,
            reserved=0,
            fulfilled=0,
        )

        self.url = "/api/v1/reservations/"

    def test_successful_reservation(self):
        response = self.client.post(
            self.url,
            {"product_id": self.product.product_id},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Reservation.objects.count(), 1)

        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.available, 2)
        self.assertEqual(self.inventory.reserved, 1)

        self.assertIn("reservation_id", response.data)
        self.assertIn("product_id", response.data)
        self.assertIn("status", response.data)
        self.assertIn("reserved_at", response.data)

    def test_reservation_of_last_available_unit(self):
        self.inventory.available = 1
        self.inventory.save()

        response = self.client.post(
            self.url,
            {"product_id": self.product.product_id},
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.available, 0)
        self.assertEqual(self.inventory.reserved, 1)

    def test_reservation_fails_when_inventory_is_zero(self):
        self.inventory.available = 0
        self.inventory.save()

        response = self.client.post(
            self.url,
            {"product_id": self.product.product_id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Reservation.objects.count(), 0)

        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.available, 0)
        self.assertEqual(self.inventory.reserved, 0)

    def test_reservation_fails_without_inventory_record(self):
        self.inventory.delete()

        response = self.client.post(
            self.url,
            {"product_id": self.product.product_id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_reservation_fails_when_product_id_is_missing(self):
        response = self.client.post(
            self.url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_reservation_fails_when_product_id_is_invalid(self):
        response = self.client.post(
            self.url,
            {"product_id": "abc"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_reservation_fails_when_product_id_is_not_positive(self):
        for product_id in (0, -1):
            with self.subTest(product_id=product_id):
                response = self.client.post(
                    self.url,
                    {"product_id": product_id},
                    format="json",
                )

                self.assertEqual(response.status_code, 400)

        self.assertEqual(Reservation.objects.count(), 0)

    def test_get_method_is_not_allowed(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
