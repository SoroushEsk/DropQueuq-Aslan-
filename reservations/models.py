from django.db import models

# Create your models here.
class Reservation(models.Model):
    reservation_id = models.AutoField(primary_key=True)
    product_id = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="reservations")
    reserved_at = models.DateTimeField(auto_now_add=True)
    
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        EXPIRED = "expired", "Expired"
        CONFIRM = "confirm", "Confirm"
        
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
