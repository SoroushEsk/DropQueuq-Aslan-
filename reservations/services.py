from django.db import transaction
from django.core.exceptions import ValidationError

from catalog.models import Product
from inventory.models import Inventory
from .models import Reservation

@transaction.atomic
def create_reservation(product_id):
    inventory = (
        Inventory.objects
        .select_for_update()
        .filter(product_id=product_id)
        .first()
    )
    
    if inventory == None:
        raise ValidationError("Inventory record not found!")
    
    if inventory.available <= 0:
        raise ValidationError("Item is sold out")
    
    inventory.available -= 1
    inventory.reserved += 1
    inventory.save(update_fields=["available", "reserved"])
    
    reservation = Reservation.objects.create(
        product_id_id=product_id,
        status=Reservation.Status.PENDING
    )
    
    return reservation
    