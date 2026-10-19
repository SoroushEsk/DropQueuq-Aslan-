from django.db import models

# Create your models here.
class Product(models.Model):
    product_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=32)
    reservation_expiring_time_by_min = models.IntegerField(default=2)


    
    def __str__(self):
        return f"id: {self.product_id}, name: {self.name},  reservation_time: {self.reservation_expiring_time_by_min}"