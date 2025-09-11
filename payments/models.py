from django.db import models

# Create your models here.
# models.py
from django.db import models

class ProductPrice(models.Model):
    product_id = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")

    def __str__(self):
        return f"{self.product_id} - {self.price} {self.currency}"
