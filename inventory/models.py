from django.db import models

# Create your models here.
class Inventory(models.Model):
    inventory_id = models.AutoField(primary_key=True)
    product_id = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="inventory")
    on_hand = models.IntegerField()
    available = models.IntegerField()
    reserved = models.IntegerField(default=0)
    fulfilled = models.IntegerField(default=0)