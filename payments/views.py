import logging
import json
import requests
from django.views import View
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
from django.shortcuts import redirect
from .paypal_api import PayPalClient

PRODUCT_STORE = {}
logger = logging.getLogger(__name__)

# ✅ Use one PayPalClient instance globally
paypal_client = PayPalClient()


@method_decorator(csrf_exempt, name='dispatch')
class OAuthTokenView(View):
    def get(self, request):
        """Render the OAuth token form."""
        return render(request, 'payments/oauth_token.html')

    def post(self, request):
        """Fetch PayPal OAuth token."""
        url = f"{settings.PAYPAL_BASE_URL}/v1/oauth2/token"
        auth = (settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET)
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}

        try:
            response = requests.post(url, headers=headers, data=data, auth=auth)
            response.raise_for_status()
            response_data = response.json()
            logger.info("PayPal API response: %s", response_data)

            return render(request, 'payments/oauth_token.html', {
                'response': {"ok": True, "data": json.dumps(response_data, indent=2)}
            })

        except requests.RequestException as e:
            logger.error("PayPal API error: %s, Response: %s", str(e), response.text)
            return render(request, 'payments/oauth_token.html', {
                'response': {"ok": False, "error": str(e), "details": response.text}
            })


@method_decorator(csrf_exempt, name='dispatch')
class CreateProductView(View):
    def get(self, request):
        """Render the create product form."""
        return render(request, 'payments/create_product.html')

    def post(self, request):
        try:
            name = request.POST.get("name", "").strip()
            description = request.POST.get("description", "").strip()
            product_type = request.POST.get("type", "").strip()

            if not name or not product_type:
                return render(request, 'payments/create_product.html', {
                    'response': {
                        "ok": False,
                        "error": "Missing required fields",
                        "details": "Product name and type are required"
                    }
                })

            # ✅ Create product in PayPal
            result = paypal_client.create_product(
                name=name,
                description=description,
                ptype=product_type
            )

            if result["ok"]:
                product_id = result["data"]["id"]
                logger.info(f"✅ Product created on PayPal: {result['data']}")

                # ✅ Redirect to create-order page for this product
                return redirect(f"/paypal/create-order/?product_id={product_id}")

            # Failed to create product
            return render(request, 'payments/create_product.html', {
                'response': {
                    "ok": False,
                    "error": "Failed to create product",
                    "details": result.get("error", "Unknown error")
                }
            })

        except Exception as e:
            return render(request, 'payments/create_product.html', {
                'response': {
                    "ok": False,
                    "error": str(e),
                    "details": "Failed to create product"
                }
            })



@method_decorator(csrf_exempt, name='dispatch')
class ListProductsView(View):
    def get(self, request):
        """Fetch and display PayPal products with pagination and pretty JSON."""
        try:
            token = paypal_client.get_access_token()
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            all_products = []
            page = 1
            page_size = 10  # You can increase this if needed

            while True:
                url = f"{settings.PAYPAL_BASE_URL}/v1/catalogs/products?page_size={page_size}&page={page}"
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()

                if "products" in data:
                    all_products.extend(data["products"])

                # Check if there is a next page
                next_link = next((link["href"] for link in data.get("links", []) if link["rel"] == "next"), None)
                if not next_link:
                    break

                page += 1

            # Pretty-print JSON
            pretty_data = json.dumps({"products": all_products}, indent=4)

            return render(request, 'payments/list_products.html', {
                'response': {"ok": True, "data": pretty_data}
            })

        except requests.RequestException as e:
            logger.error("PayPal API error: %s", str(e))
            return render(request, 'payments/list_products.html', {
                'response': {"ok": False, "error": str(e), "details": getattr(response, 'text', '')}
            })


from .models import ProductPrice 

@method_decorator(csrf_exempt, name='dispatch')
class CreateOrderFormView(View):
    def get(self, request):
        """Render order form with product_id passed from create_product."""
        product_id = request.GET.get("product_id")
        return render(request, "payments/create_order.html", {"product_id": product_id})

    def post(self, request):
        """Create order for a given product + price and save to DB."""
        product_id = request.POST.get("product_id")
        price = request.POST.get("price")
        currency = request.POST.get("currency", "USD")

        if not product_id or not price:
            return render(request, "payments/create_order.html", {
                "error": "Product ID and price are required",
                "product_id": product_id
            })

        # 1️⃣ Create order in PayPal
        result = paypal_client.create_order(product_id, price, currency)

        if result["ok"]:
            # 2️⃣ Save to DB
            ProductPrice.objects.update_or_create(
                product_id=product_id,
                defaults={"price": price, "currency": currency}
            )

        return render(request, "payments/create_order.html", {
            "product_id": product_id,
            "response": result
        })


class ProductPricesJSONView(View):
    def get(self, request):
        items = list(ProductPrice.objects.values("product_id", "price", "currency"))
        return JsonResponse({"count": len(items), "items": items})
