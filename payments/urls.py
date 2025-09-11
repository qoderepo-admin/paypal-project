from django.urls import path
from .views import OAuthTokenView, CreateProductView, ListProductsView,CreateOrderFormView

app_name = 'payments'

urlpatterns = [
    path('oauth/token/', OAuthTokenView.as_view(), name='oauth_token'),
    path('products/create/', CreateProductView.as_view(), name='create_product'),
    path('products/', ListProductsView.as_view(), name='list_products'),
    path("create-order/", CreateOrderFormView.as_view(), name="create-order"),

    
]