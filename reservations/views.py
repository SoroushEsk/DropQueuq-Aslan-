from django.shortcuts import render, redirect
from .services import create_reservation


# Create your views here.
def make_reservation(request, product_id):
    if request.method == "POST":
        try:
            reservation = create_reservation(product_id)
            # todo: send a success message to outbox
        except:
            # todo: send a failiur message to outbox
            pass
        
            