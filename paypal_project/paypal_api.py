import time
import requests
from django.conf import settings


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
                       home_url: str | None = None):
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
        token = self.get_access_token()
        url = f"{self.base_url}/v1/catalogs/products"
        params = {"page_size": page_size, "page": page, "total_required": str(total_required).lower()}
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code != 200:
            return {"ok": False, "status": response.status_code, "error": response.text}
        return {"ok": True, "status": 200, "data": response.json()}

    def list_all_products(self, page_size: int = 20, max_pages: int | None = None):
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
                "pages_fetched": total_pages_fetched
            }
        }

    # Invoicing catalog items (v2)
    def list_invoicing_items(self, page_size: int = 20, page: int = 1):
        token = self.get_access_token()
        url = f"{self.base_url}/v2/invoicing/catalogs/items"
        params = {"page_size": min(page_size, 50), "page": max(page, 1)}
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code != 200:
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": 200, "data": resp.json()}

    def list_all_invoicing_items(self, page_size: int = 20, max_pages: int | None = None):
        items = []
        page = 1
        pages_fetched = 0
        while True:
            try:
                res = self.list_invoicing_items(page_size=page_size, page=page)
                if not res.get("ok"):
                    break
                data = res.get("data", {})
                page_items = data.get("items", []) or data.get("products", []) or []
                if not page_items:
                    break
                items.extend(page_items)
                pages_fetched += 1
                if max_pages and pages_fetched >= max_pages:
                    break
                if len(page_items) < page_size:
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
                "items": items,
                "total_items": len(items),
                "pages_fetched": pages_fetched,
            },
        }

    def create_invoicing_item(self, name: str, description: str | None, currency: str, value: str,
                               item_code: str | None = None):
        token = self.get_access_token()
        url = f"{self.base_url}/v2/invoicing/catalogs/items"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "name": name[:127],
            "description": (description or "")[:256],
            "unit_amount": {"currency_code": currency, "value": str(value)},
        }
        if item_code:
            payload["item_code"] = item_code[:127]
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code not in (200, 201):
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}

    def delete_invoicing_item(self, item_id: str):
        token = self.get_access_token()
        url = f"{self.base_url}/v2/invoicing/catalogs/items/{item_id}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.delete(url, headers=headers, timeout=30)
        if resp.status_code not in (200, 204):
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": resp.status_code}

    def delete_all_invoicing_items(self):
        res = self.list_all_invoicing_items(page_size=50)
        if not res.get("ok"):
            return res
        items = res.get("data", {}).get("items", [])
        errors = []
        for it in items:
            iid = it.get("id")
            if not iid:
                continue
            r = self.delete_invoicing_item(iid)
            if not r.get("ok"):
                errors.append({"id": iid, "error": r.get("error"), "status": r.get("status")})
        if errors:
            return {"ok": False, "errors": errors}
        return {"ok": True, "deleted": len(items)}

    def search_items_by_name(self, search_term: str, exact_match: bool = False):
        from difflib import SequenceMatcher
        res = self.list_all_invoicing_items()
        if not res.get("ok"):
            return []
        all_items = res.get("data", {}).get("items", [])
        term = (search_term or "").lower().strip()
        exact, partial, fuzzy = [], [], []
        for it in all_items:
            nm = (it.get("name") or "").lower().strip()
            if not nm:
                continue
            if nm == term:
                exact.append(it)
            elif not exact_match and (term in nm or nm in term):
                partial.append(it)
            else:
                ratio = SequenceMatcher(None, nm, term).ratio()
                if ratio >= 0.6:
                    fuzzy.append((ratio, it))
        if exact or partial:
            return exact + partial
        fuzzy.sort(key=lambda x: x[0], reverse=True)
        return [p for _r, p in fuzzy[:5]]

    def get_item_suggestions(self, search_term: str, max_suggestions: int = 5):
        res = self.list_all_invoicing_items()
        if not res.get("ok"):
            return []
        all_items = res.get("data", {}).get("items", [])
        words = set((search_term or "").lower().split())
        sugg = []
        seen = set()
        for it in all_items:
            nm = (it.get("name") or "").strip()
            low = nm.lower()
            if nm and low not in seen and words.intersection(set(low.split())):
                sugg.append(nm)
                seen.add(low)
            if len(sugg) >= max_suggestions:
                break
        return sugg

    # Invoices (v2)
    def create_invoice(self, recipient_email: str, items: list[dict], currency: str = "USD"):
        token = self.get_access_token()
        url = f"{self.base_url}/v2/invoicing/invoices"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "detail": {"currency_code": currency},
            "primary_recipients": [{"billing_info": {"email_address": recipient_email}}],
            "items": items,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code not in (200, 201):
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": resp.status_code, "data": resp.json()}

    def send_invoice(self, invoice_id: str):
        token = self.get_access_token()
        url = f"{self.base_url}/v2/invoicing/invoices/{invoice_id}/send"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.post(url, json={}, headers=headers, timeout=30)
        if resp.status_code not in (200, 202):
            return {"ok": False, "status": resp.status_code, "error": resp.text}
        return {"ok": True, "status": resp.status_code}

    def create_and_send_invoice(self, recipient_email: str, items: list[dict], currency: str = "USD"):
        created = self.create_invoice(recipient_email, items, currency=currency)
        if not created.get("ok"):
            return created
        inv_id = created.get("data", {}).get("id")
        if not inv_id:
            return {"ok": False, "error": "No invoice id returned"}
        sent = self.send_invoice(inv_id)
        if not sent.get("ok"):
            return sent | {"invoice_id": inv_id}
        return {"ok": True, "invoice_id": inv_id}

