#!/usr/bin/env python3
"""
Wipe and seed PayPal Invoicing Catalog Items from the American menu.

Usage:
  python scripts/seed_invoicing_catalog.py

Environment:
  - Uses Django settings to read PAYPAL_* from .env
  - PAYPAL_BASE_URL should point to Sandbox for POC

This will DELETE ALL existing invoicing catalog items in the account.
"""

import os
import sys
import re
from typing import Tuple

# Configure Django so we can reuse PayPalClient and .env settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paypal_project.settings")
import django  # type: ignore
django.setup()

from paypal_project.paypal_api import PayPalClient  # noqa: E402
from scripts.american_menu_payloads import american_menu  # noqa: E402


def slugify(text: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return t[:60] if t else "item"


def seed() -> Tuple[int, int]:
    client = PayPalClient()

    print("Deleting all existing invoicing catalog items …", flush=True)
    wiped = client.delete_all_invoicing_items()
    if not wiped.get("ok"):
        print(f"Failed to wipe catalog: {wiped}")
        sys.exit(1)
    print(f"Deleted items: {wiped.get('deleted', 0)}")

    items = american_menu()
    created = 0
    failed = 0
    for m in items:
        name = m.name
        desc = m.description
        currency = (m.currency or "USD").upper()
        value = f"{float(m.suggested_price):.2f}"
        code = slugify(name)
        res = client.create_invoicing_item(name=name, description=desc, currency=currency, value=value, item_code=code)
        if res.get("ok"):
            created += 1
        else:
            failed += 1
            print(f"Failed to create {name}: {res}")

    print(f"Created {created} items; failed {failed}")
    return created, failed


if __name__ == "__main__":
    seed()
