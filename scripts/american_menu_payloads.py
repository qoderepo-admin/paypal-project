#!/usr/bin/env python3
"""
Generate PayPal Catalog product payloads for an American restaurant menu.

This script DOES NOT call any APIs. It prints a JSON array of payloads that
match the body you can send to PayPal's create product endpoint (via your
existing create_product helper).

Usage:
  python scripts/american_menu_payloads.py > menu_payloads.json

Optional env:
  CURRENCY (default: USD)

Later, to create products, iterate over the payloads and send them to your
PayPal client, or use curl with a valid access token.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import json
import os
import sys
from pathlib import Path


DEFAULT_CURRENCY = os.getenv("CURRENCY", "USD").strip() or "USD"


@dataclass
class MenuItem:
    name: str
    description: str
    category: str  # local category label (e.g., burger, sandwich, pizza, etc.)
    suggested_price: float  # kept locally; PayPal product itself has no price
    currency: str = DEFAULT_CURRENCY

    def to_paypal_payload(self) -> Dict[str, Any]:
        """Build a PayPal create_product payload (without price)."""
        # Your PayPal client uses type="SERVICE" by default; keep consistent.
        payload = {
            "name": self.name[:127],  # API name length guard
            "description": self.description[:256],
            "type": "SERVICE",
            # The PayPal API allows an optional "category" string. We'll include
            # the local category label for convenience.
            "category": self.category,
        }
        return payload

    def to_local_price_row(self) -> Dict[str, Any]:
        """Local helper for your DB seeding (not PayPal)."""
        return {
            "product_name": self.name,
            "price": f"{self.suggested_price:.2f}",
            "currency": self.currency,
            "category": self.category,
        }


def american_menu() -> List[MenuItem]:
    items: List[MenuItem] = []

    # Appetizers
    items += [
        MenuItem("Buffalo Wings (8 pc)", "Crispy wings tossed in buffalo sauce with blue cheese dip.", "appetizer", 8.99),
        MenuItem("Mozzarella Sticks", "Golden fried mozzarella with marinara sauce.", "appetizer", 7.99),
        MenuItem("Loaded Nachos Supreme", "Tortilla chips with cheddar, jalapeños, salsa, and sour cream.", "appetizer", 10.99),
        MenuItem("Classic Caesar Salad", "Romaine, parmesan, and croutons with Caesar dressing.", "salad", 7.49),
    ]

    # Burgers
    items += [
        MenuItem("Classic Cheeseburger", "Beef patty, cheddar, lettuce, tomato, pickle, and house sauce.", "burger", 11.99),
        MenuItem("Bacon BBQ Burger", "Smoky bacon, cheddar, BBQ sauce, and crispy onions.", "burger", 13.49),
        MenuItem("Mushroom Swiss Burger", "Sautéed mushrooms, Swiss cheese, and garlic aioli.", "burger", 12.99),
        MenuItem("Veggie Black Bean Burger", "Grilled black bean patty with avocado and chipotle mayo.", "burger", 11.49),
        MenuItem("Double Stack Burger", "Two beef patties, American cheese, and special sauce.", "burger", 14.49),
    ]

    # Sandwiches
    items += [
        MenuItem("Philly Cheesesteak", "Shaved steak, peppers, onions, and provolone on a hoagie.", "sandwich", 12.99),
        MenuItem("Grilled Chicken Sandwich", "Marinated chicken breast with lettuce, tomato, and mayo.", "sandwich", 11.99),
        MenuItem("BLT Sandwich", "Bacon, lettuce, tomato, and mayo on toasted bread.", "sandwich", 10.49),
        MenuItem("Pulled Pork Sandwich", "Slow-cooked BBQ pork with coleslaw on a brioche bun.", "sandwich", 12.49),
    ]

    # Burritos
    items += [
        MenuItem("Classic Beef Burrito", "Seasoned ground beef, rice, beans, cheddar, and pico de gallo wrapped in a warm tortilla.", "burrito", 10.99),
        MenuItem("Grilled Chicken Burrito", "Grilled chicken, cilantro-lime rice, black beans, cheese, and salsa.", "burrito", 10.49),
        MenuItem("Veggie Burrito", "Grilled peppers and onions, rice, black beans, corn, guacamole, and salsa fresca.", "burrito", 9.99),
        MenuItem("California Burrito", "Carne asada, french fries, cheddar, guacamole, and sour cream.", "burrito", 12.49),
        MenuItem("Breakfast Burrito", "Scrambled eggs, bacon, potatoes, cheddar, and salsa roja.", "burrito", 9.49),
    ]

    # Personal Pizzas
    items += [
        MenuItem("Margherita Personal Pizza", "Tomato, fresh mozzarella, and basil.", "pizza", 11.99),
        MenuItem("Pepperoni Personal Pizza", "Tomato sauce, mozzarella, and pepperoni.", "pizza", 12.99),
        MenuItem("BBQ Chicken Personal Pizza", "BBQ sauce, chicken, red onion, and cilantro.", "pizza", 13.49),
    ]

    # Sides
    items += [
        MenuItem("French Fries", "Crispy shoestring fries with sea salt.", "side", 3.99),
        MenuItem("Sweet Potato Fries", "Seasoned sweet potato fries with chipotle dip.", "side", 4.49),
        MenuItem("Onion Rings", "Beer-battered rings with ranch dip.", "side", 4.99),
        MenuItem("Coleslaw", "Creamy cabbage slaw.", "side", 3.49),
    ]

    # Desserts
    items += [
        MenuItem("Warm Apple Pie", "Classic spiced apple filling with flaky crust.", "dessert", 5.99),
        MenuItem("Chocolate Brownie Sundae", "Warm brownie with vanilla ice cream and chocolate sauce.", "dessert", 6.99),
        MenuItem("New York Cheesecake", "Rich and creamy classic cheesecake.", "dessert", 6.49),
    ]

    # Drinks
    items += [
        MenuItem("Fountain Soda", "Assorted flavors.", "drink", 2.99),
        MenuItem("Iced Tea", "Freshly brewed.", "drink", 2.99),
        MenuItem("Fresh Lemonade", "House-made lemonade.", "drink", 3.49),
        MenuItem("Vanilla Milkshake", "Hand-spun vanilla milkshake.", "drink", 5.49),
    ]

    return items


def build_output() -> Dict[str, Any]:
    items = american_menu()
    payloads = [it.to_paypal_payload() for it in items]
    local_prices = [it.to_local_price_row() for it in items]
    return {
        "count": len(items),
        "paypal_create_product_payloads": payloads,
        "local_price_suggestions": local_prices,
    }


def main() -> None:
    out = build_output()
    print(json.dumps(out, indent=2))

    # Execute API operations per TODO:
    # 1) Delete all available products first (Note: Catalog Products API does not support delete).
    # 2) Create new products using the payloads generated above.
    # 3) Create/Update Plans (pricing) for the products created above.

    try:
        # Ensure we can import the Django-based PayPal client
        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paypal_project.settings")

        from paypal_project.paypal_api import PayPalClient

        client = PayPalClient()

        # Step 1: Attempt cleanup (no direct delete for catalog products)
        print("[INFO] Step 1: Cleanup existing products (delete not supported; listing only)...")
        existing = client.list_all_products(page_size=20)
        if existing.get("ok"):
            total_exist = (existing.get("data") or {}).get("total_items", 0)
            print(f"[INFO] Found {total_exist} existing products. Catalog Products API has no delete; skipping.")
        else:
            print(f"[WARN] Could not list existing products: {existing.get('error')}")

        # Build price map by name
        name_to_price: dict[str, tuple[str, str]] = {}
        for row in out.get("local_price_suggestions", []):
            nm = row.get("product_name")
            val = row.get("price")
            cur = (row.get("currency") or "USD").upper()
            if nm and val:
                name_to_price[nm] = (str(val), cur)

        # Step 2: Create products from payloads
        print("[INFO] Step 2: Creating products from payloads...")
        created: list[dict] = []
        for payload in out.get("paypal_create_product_payloads", []):
            nm = payload.get("name")
            resp = client.create_product(
                name=nm or "Unnamed",
                description=payload.get("description") or "",
                ptype=payload.get("type") or "SERVICE",
                category=payload.get("category"),
                image_url=payload.get("image_url"),
                home_url=payload.get("home_url"),
            )
            if not resp.get("ok"):
                print(f"[ERROR] Failed to create product '{nm}': {resp.get('status')} {resp.get('error')}")
                continue
            pdata = (resp.get("data") or {})
            pid = pdata.get("id")
            created.append({"id": pid, "name": nm})
            print(f"[OK] Created product: {nm} -> {pid}")

        # Step 3: Create plans (pricing) for created products
        print("[INFO] Step 3: Creating plans (pricing) for created products...")
        plans_created = 0
        for item in created:
            nm = item.get("name")
            pid = item.get("id")
            if not pid:
                continue
            price_val, price_cur = name_to_price.get(nm, (None, None))
            if not price_val or not price_cur:
                print(f"[WARN] No price found for '{nm}', skipping plan creation.")
                continue
            plan_name = f"Plan for {nm}"
            plan_desc = f"Recurring price for {nm}"
            pres = client.create_plan(
                product_id=pid,
                name=plan_name[:127],
                description=plan_desc[:256],
                currency=price_cur,
                value=str(price_val),
                interval_unit="MONTH",
                interval_count=1,
            )
            if not pres.get("ok"):
                print(f"[ERROR] Failed to create plan for '{nm}': {pres.get('status')} {pres.get('error')}")
                continue
            pdat = pres.get("data") or {}
            print(f"[OK] Created plan for '{nm}': {pdat.get('id')}")
            plans_created += 1

        print(f"[SUMMARY] Products created: {len(created)}; Plans created: {plans_created}")
    except Exception as e:
        print(f"[ERROR] Main flow error: {e}")

if __name__ == "__main__":
    main()
