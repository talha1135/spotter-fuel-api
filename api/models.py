from django.db import models


class FuelStation(models.Model):
    opis_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    retail_price = models.DecimalField(max_digits=8, decimal_places=5)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        indexes = [
            models.Index(fields=["state"]),
            models.Index(fields=["latitude", "longitude"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state})"