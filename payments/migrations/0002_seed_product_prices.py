from django.db import migrations
from decimal import Decimal


def seed_prices(apps, schema_editor):
    ProductPrice = apps.get_model('payments', 'ProductPrice')

    rows = [
        ("PROD-5GY20324CX0648208", Decimal("10.00"), "USD"),
        ("PROD-9XR53003ST8225906", Decimal("10.00"), "USD"),
        ("PROD-8NK02551FX155434L", Decimal("10.00"), "USD"),
        ("PROD-54A732069A9174246", Decimal("50.00"), "USD"),
        ("PROD-3JJ0602045909980E", Decimal("40.00"), "USD"),
        ("PROD-51456766PL486974M", Decimal("30.00"), "USD"),
    ]

    for product_id, price, currency in rows:
        ProductPrice.objects.update_or_create(
            product_id=product_id,
            defaults={
                'price': price,
                'currency': currency,
            },
        )


def unseed_prices(apps, schema_editor):
    ProductPrice = apps.get_model('payments', 'ProductPrice')
    product_ids = [
        "PROD-5GY20324CX0648208",
        "PROD-9XR53003ST8225906",
        "PROD-8NK02551FX155434L",
        "PROD-54A732069A9174246",
        "PROD-3JJ0602045909980E",
        "PROD-51456766PL486974M",
    ]
    ProductPrice.objects.filter(product_id__in=product_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_prices, reverse_code=unseed_prices),
    ]

