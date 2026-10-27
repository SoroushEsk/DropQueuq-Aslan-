"""Reservation API serializers will be added after the API contract is implemented."""

from rest_framework import serializers
import uuid


class ReservationCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)


def validate_idempotency_key(value):
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise serializers.ValidationError(
            "A valid Idempotency-Key UUID is required."
        )