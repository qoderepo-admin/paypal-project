import time
import requests
from django.conf import settings

# REVIEW NOTES (non-functional comments only):
# - Catalog scope: This client should only expose Catalog Products (v1) + Billing Plans (v1),
#   which aligns with the project requirement "only items and their plans (price)".
# - Idempotency & representations: For create operations (products/plans), consider adding
#   headers like "PayPal-Request-Id" (idempotency) and "Prefer: return=representation"
#   to make POSTs safe to retry and to receive full resource bodies.
# - Error handling: Some methods return error text; optionally parse JSON error bodies to
#   surface structured details (name/message/details) when available.
# - Timeouts/retries: Requests specify a timeout; consider adding lightweight retry/backoff
#   for transient 5xx/429 responses.


class PayPalClient:
    def __init__(self):
        self._token_cache = {"access_token": None, "expires_at": 0}
        self.base_url = settings.PAYPAL_BASE_URL

    def _now(self):
        return int(time.time())

    def get_access_token(self):
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

    # Catalog Products (v1) — retained for backward compatibility
    def create_product(self, name: str, description: str = "", ptype: str = "SERVICE",
                       category: str | None = None, image_url: str | None = None,
                       home_url: str | None = None, paypal_request_id: str | None = None):
        # TODO(review): Optionally enforce length guards here (name<=127, description<=256)
        #   similar to the scripts, so the API never rejects long strings.
        # TODO(review): Consider adding headers:
        #   - "Prefer": "return=representation" to receive full product object on creation.
        #   - "PayPal-Request-Id": a stable unique id for idempotency.
        token = self.get_access_token()
        url = f"{self.base_url}/v1/catalogs/products"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if paypal_request_id:
            headers["PayPal-Request-Id"] = str(paypal_request_id)

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
        token = self.get_access_token()
        url = f"{self.base_url}/v1/catalogs/products"
        params = {"page_size": page_size, "page": page, "total_required": str(total_required).lower()}
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code != 200:
            return {"ok": False, "status": response.status_code, "error": response.text}
        return {"ok": True, "status": 200, "data": response.json()}

    def list_all_products(self, page_size: int = 20, max_pages: int | None = None):
        all_products: list[dict] = []
        page = 1
        total_pages_fetched = 0
        effective_page_size = min(max(page_size, 1), 20)

        while True:
            try:
                result = self.list_products(page_size=effective_page_size, page=page, total_required=True)
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
                    estimated_total_pages = (total_items + effective_page_size - 1) // effective_page_size
                    if page >= estimated_total_pages:
                        break
                if len(products_on_page) < effective_page_size:
                    break
                page += 1
            except requests.exceptions.RequestException:
                break
            except Exception:
                break

        return {
            "ok": True,
            "status": 200,
            "data": {
                "products": all_products,
                "total_items": len(all_products),
                "pages_fetched": total_pages_fetched,
            },
        }

    def search_items_by_name(self, search_term: str, exact_match: bool = False):
        """Search catalog products by name with optional exact match or fuzzy fallback.

        Returns a list of product dicts as provided by PayPal list endpoints.
        """
        from difflib import SequenceMatcher
        term = (search_term or "").lower().strip()
        if not term:
            return []
        res = self.list_all_products()
        if not res.get("ok"):
            return []
        products = (res.get("data", {}) or {}).get("products", [])
        if exact_match:
            return [p for p in products if (p.get("name") or "").lower().strip() == term]
        partial = [p for p in products if term in (p.get("name") or "").lower()]
        if partial:
            return partial
        scored = []
        for p in products:
            nm = (p.get("name") or "").lower().strip()
            if not nm:
                continue
            r = SequenceMatcher(None, nm, term).ratio()
            if r >= 0.6:
                scored.append((r, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _r, p in scored[:5]]

    def get_item_suggestions(self, search_term: str, max_suggestions: int = 5):
        """Suggest product names by simple word-overlap on catalog products."""
        res = self.list_all_products()
        if not res.get("ok"):
            return []
        products = (res.get("data", {}) or {}).get("products", [])
        words = set((search_term or "").lower().split())
        sugg: list[str] = []
        seen: set[str] = set()
        for p in products:
            nm = (p.get("name") or "").strip()
            low = nm.lower()
            if nm and low not in seen and (not words or words.intersection(set(low.split()))):
                sugg.append(nm)
                seen.add(low)
            if len(sugg) >= max_suggestions:
                break
        return sugg

        # Billing Plans (v1)
    def create_plan(self, product_id: str, name: str, description: str,
                    currency: str, value: str, interval_unit: str = "MONTH", interval_count: int = 1,
                    paypal_request_id: str | None = None):
        # TODO(review): After creation, plans are often returned in CREATED state and must be
        #   ACTIVATED before use. Consider adding a helper to activate/deactivate plans or
        #   document the expected lifecycle for callers.
        # TODO(review): Consider idempotency + prefer headers as with products.
        token = self.get_access_token()
        url = f"{self.base_url}/v1/billing/plans"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if paypal_request_id:
            headers["PayPal-Request-Id"] = str(paypal_request_id)

        payload = {
            "product_id": product_id,
            "name": name,
            "description": description,
            "billing_cycles": [
                {
                    "frequency": {
                        "interval_unit": interval_unit,
                        "interval_count": interval_count
                    },
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": str(value),
                            "currency_code": currency
                        }
                    }
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee_failure_action": "CANCEL",
                "payment_failure_threshold": 3
            }
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code not in (200, 201):
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}

    def get_plan(self, plan_id: str):
        token = self.get_access_token()
        url = f"{self.base_url}/v1/billing/plans/{plan_id}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": 200, "data": resp.json()}

    def list_plans(self, product_id: str | None = None, page_size: int = 10, page: int = 1):
        token = self.get_access_token()
        url = f"{self.base_url}/v1/billing/plans"
        effective_page_size = min(max(page_size, 1), 20)
        params = {"page_size": effective_page_size, "page": max(page, 1)}
        if product_id:
            params["product_id"] = product_id # pyright: ignore[reportArgumentType]
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code != 200:
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": 200, "data": resp.json()}

    def update_plan_pricing(self, plan_id: str, currency: str, value: str, paypal_request_id: str | None = None):
        token = self.get_access_token()
        url = f"{self.base_url}/v1/billing/plans/{plan_id}/update-pricing-schemes"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if paypal_request_id:
            headers["PayPal-Request-Id"] = str(paypal_request_id)
        payload = {
            "pricing_schemes": [
                {
                    "billing_cycle_sequence": 1,
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": str(value),
                            "currency_code": currency
                        }
                    }
                }
            ]
        }
        # TODO(review): Consider using a unique "PayPal-Request-Id" for idempotency on pricing updates.
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code not in (200, 204):
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": resp.status_code}
