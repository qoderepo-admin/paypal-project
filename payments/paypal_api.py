import time
import requests
from django.conf import settings

class PayPalClient:
    def __init__(self):
        self._token_cache = {"access_token": None, "expires_at": 0}
        self.base_url = settings.PAYPAL_BASE_URL

    def _now(self):
        """Return current time as Unix timestamp."""
        return int(time.time())

    def get_access_token(self):
        """Retrieve or return cached PayPal access token."""
        if self._token_cache["access_token"] and self._token_cache["expires_at"] > self._now():
            return self._token_cache["access_token"]

        url = f"{self.base_url}/v1/oauth2/token"
        auth = (settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET)

        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}

        response = requests.post(url, headers=headers, data=data, auth=auth)
        response.raise_for_status()

        token_data = response.json()
        self._token_cache["access_token"] = token_data["access_token"]
        self._token_cache["expires_at"] = self._now() + token_data.get("expires_in", 3600) - 60

        return self._token_cache["access_token"]

    def create_product(self, name: str, description: str = "", ptype: str = "SERVICE",
                      category: str | None = None, image_url: str | None = None,
                      home_url: str | None = None):
        """Create a PayPal product."""
        token = self.get_access_token()
        url = f"{self.base_url}/v1/catalogs/products"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        payload = {
            "name": name,
            "description": description,
            "type": ptype,
        }
        if category:
            payload["category"] = category
        if image_url:
            payload["image_url"] = image_url
        if home_url:
            payload["home_url"] = home_url

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code not in (200, 201):
            return {"ok": False, "status": response.status_code, "error": response.text}
        return {"ok": True, "status": response.status_code, "data": response.json()}

    def list_products(self, page_size: int = 10, page: int = 1, total_required: bool = True):
        """List PayPal products (single page - kept for backward compatibility)."""
        token = self.get_access_token()
        url = f"{self.base_url}/v1/catalogs/products"
        params = {"page_size": page_size, "page": page, "total_required": str(total_required).lower()}
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code != 200:
            return {"ok": False, "status": response.status_code, "error": response.text}
        return {"ok": True, "status": 200, "data": response.json()}

    def list_all_products(self, page_size: int = 20, max_pages: int | None = None):
        """
        List ALL PayPal products across all pages with pagination.
        """
        all_products = []
        page = 1
        total_pages_fetched = 0

        while True:
            try:
                result = self.list_products(page_size=min(page_size, 20), page=page, total_required=True)
                
                if not result.get("ok"):
                    break
                
                page_data = result.get("data", {})
                products_on_page = page_data.get("products", [])
                
                if not products_on_page:
                    break
                
                all_products.extend(products_on_page)
                total_pages_fetched += 1
                
                if max_pages and total_pages_fetched >= max_pages:
                    break
                
                total_items = page_data.get("total_items", 0)
                if total_items > 0:
                    estimated_total_pages = (total_items + page_size - 1) // page_size
                    if page >= estimated_total_pages:
                        break
                
                if len(products_on_page) < page_size:
                    break
                
                page += 1
                
            except requests.exceptions.RequestException as e:
                break
            except Exception as e:
                break
        
        return {
            "ok": True,
            "status": 200,
            "data": {
                "products": all_products,
                "total_items": len(all_products),
                "pages_fetched": total_pages_fetched
            }
        }

    def search_products_by_name(self, search_term: str, exact_match: bool = False):
        """
        Search for products by name across ALL pages.
        - Exact and partial contains matching
        - Fuzzy fallback for typos (e.g., "burrito" vs "burito")
        """
        from difflib import SequenceMatcher

        result = self.list_all_products()
        if not result.get("ok"):
            return []

        all_products = result.get("data", {}).get("products", [])
        search_term_lower = search_term.lower().strip()

        exact_matches = []
        partial_matches = []
        fuzzy_candidates = []

        for product in all_products:
            product_name = (product.get("name") or "").lower().strip()

            if not product_name:
                continue

            if product_name == search_term_lower:
                exact_matches.append(product)
            elif not exact_match and (search_term_lower in product_name or product_name in search_term_lower):
                partial_matches.append(product)
            else:
                # Fuzzy ratio for typo tolerance
                ratio = SequenceMatcher(None, product_name, search_term_lower).ratio()
                if ratio >= 0.6:
                    fuzzy_candidates.append((ratio, product))

        if exact_matches or partial_matches:
            return exact_matches + partial_matches

        # Sort fuzzy candidates by best ratio first
        fuzzy_candidates.sort(key=lambda x: x[0], reverse=True)
        return [p for _r, p in fuzzy_candidates[:5]]

    def get_product_suggestions(self, search_term: str, max_suggestions: int = 5):
        """
        Get product name suggestions based on word matching.
        """
        result = self.list_all_products()
        if not result.get("ok"):
            return []
        
        all_products = result.get("data", {}).get("products", [])
        search_words = set(search_term.lower().split())
        suggestions = []
        
        for product in all_products:
            product_name = product.get("name", "")
            product_words = set(product_name.lower().split())
            
            if search_words.intersection(product_words):
                suggestions.append(product_name)
            
            if len(suggestions) >= max_suggestions:
                break
        
        return suggestions

    def create_order(self, product_id: str, price: str, currency: str = "USD"):
        """Create a PayPal order."""
        token = self.get_access_token()
        url = f"{self.base_url}/v2/checkout/orders"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": product_id,
                    "amount": {
                        "currency_code": currency,
                        "value": price
                    }
                }
            ]
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code not in (200, 201):
            return {"ok": False, "status": response.status_code, "error": response.text}
        return {"ok": True, "status": response.status_code, "data": response.json()}
