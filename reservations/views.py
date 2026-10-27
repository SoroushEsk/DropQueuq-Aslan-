# from django.shortcuts import render, redirect
# from .services import create_reservation


# # Create your views here.
# def make_reservation(request, product_id):
#     if request.method == "POST":
#         try:
#             reservation = create_reservation(product_id)
#             # todo: send a success message to outbox
#         except:
#             # todo: send a failiur message to outbox
#             pass
        
            

from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import ReservationCreateSerializer
from .services import create_reservation


class ReservationCreateView(APIView):
    def post(self, request):
        serializer = ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            reservation = create_reservation(
                product_id=serializer.validated_data["product_id"]
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "reservation_id": reservation.reservation_id,
                "product_id": reservation.product_id_id,
                "status": reservation.status,
                "reserved_at": reservation.reserved_at,
            },
            status=status.HTTP_201_CREATED,
        )
