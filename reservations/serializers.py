"""Reservation API serializers will be added after the API contract is implemented."""

from rest_framework import serializers


class ReservationCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
