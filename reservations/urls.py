from django.urls import path, include
from .views import ReservationCreateView
# from . import views

app_name = 'reservations'
urlpatterns = [
    # path("make-reservation/<int:product_id>/", views.make_reservation, name="make_reservation"),
    path("", ReservationCreateView.as_view(), name="reservation-create"),
]
