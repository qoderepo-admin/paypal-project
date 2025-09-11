from django.contrib import admin
from .models import ProductPrice

@admin.register(ProductPrice)
class ProductPriceAdmin(admin.ModelAdmin):
    list_display = ('product_id', 'price', 'currency')
    search_fields = ('product_id',)
    list_filter = ('currency',)
