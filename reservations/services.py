from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from inventory.models import Inventory
from .models import Reservation


class IdempotencyConflict(Exception):
    """The same key was reused for a different product."""


def _existing_reservation(idempotency_key, product_id):
    reservation = Reservation.objects.filter(
        idempotency_key=idempotency_key
    ).first()

    if reservation is not None:
        if reservation.product_id_id != product_id:
            raise IdempotencyConflict

    return reservation


@transaction.atomic
def _create_reservation(product_id, idempotency_key):
    existing = _existing_reservation(idempotency_key, product_id)
    if existing is not None:
        return existing

    inventory = (
        Inventory.objects
        .select_for_update()
        .filter(product_id=product_id)
        .first()
    )

    if inventory is None:
        raise ValidationError("Inventory record not found.")

    # Check again after acquiring the inventory lock.
    existing = _existing_reservation(idempotency_key, product_id)
    if existing is not None:
        return existing

    if inventory.available <= 0:
        raise ValidationError("Insufficient inventory.")

    inventory.available -= 1
    inventory.reserved += 1
    inventory.save(update_fields=["available", "reserved"])

    return Reservation.objects.create(
        product_id_id=product_id,
        status=Reservation.Status.PENDING,
        idempotency_key=idempotency_key,
    )


def create_reservation(product_id, idempotency_key):
    try:
        return _create_reservation(
            product_id=product_id,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        # The failed atomic transaction has already rolled back.
        existing = Reservation.objects.filter(
            idempotency_key=idempotency_key
        ).first()

        if existing is None:
            raise

        if existing.product_id_id != product_id:
            raise IdempotencyConflict

        return existing