"""Single-function PayPal menu accessor + get_response tools.

This module intentionally exposes only:
- get_menu_with_prices(): one function to fetch menu items with plan prices (with 60m cache + search)
- get_response(): chatbot entry that uses the single tool
"""

import json
import logging
import os
import time
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

from paypal_project.paypal_api import PayPalClient


logger = logging.getLogger(__name__)

load_dotenv()

# OpenAI client and model
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip().strip('"').strip("'")


def _normalize_model_name(name: str | None) -> str:
    if not name:
        return "gpt-4o-mini"
    # Normalize curly/Unicode dashes to ASCII
    dashes = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
    return name.translate(str.maketrans({c: '-' for c in dashes})).strip().strip('"').strip("'")


OPENAI_MODEL = _normalize_model_name((os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip())
try:
    OPENAI_TEMPERATURE = float((os.getenv("OPENAI_TEMPERATURE") or "0.3").strip() or 0.3)
except ValueError:
    OPENAI_TEMPERATURE = 0.3

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# PayPal client (Sandbox/Live determined by settings)
pp_client = PayPalClient()

# 60-minute cache (base menu with best plan price per product)
_CACHE_TTL_SEC = 60 * 60
_MENU_CACHE: Dict[str, Any] = {"data": None, "cached_at": 0}


def get_menu_with_prices(query: str | None = None,
                         exact: bool = False,
                         limit: int | None = None) -> List[dict]:
    """Return menu items (Catalog Products) with a best plan price, with search and 60m cache.

    Caching strategy:
    - Cache the base list of all products joined to their best ACTIVE plan + price for 60 minutes.
    - Apply query/exact/limit filtering on the cached list for fast responses.
    """
    try:
        now = int(time.time())
        base = _MENU_CACHE.get("data")
        if not base or (_MENU_CACHE.get("cached_at", 0) + _CACHE_TTL_SEC) < now:
            # Rebuild base: fetch products, then plans/prices per product
            prod_res = pp_client.list_all_products()
            if not prod_res.get("ok"):
                return []
            products = (prod_res.get("data", {}) or {}).get("products", [])

            # Build rows in parallel to reduce warm time
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _build_row(prod: dict) -> dict:
                pid = prod.get("id")
                name = (prod.get("name") or "").strip()
                description = prod.get("description") or ""
                best = None  # (is_inactive, price_num, candidate)
                try:
                    lp = pp_client.list_plans(product_id=pid, page_size=20, page=1)
                    plans = (lp.get("data") or {}).get("plans") or (lp.get("data") or {}).get("items") or []
                except Exception:
                    plans = []

                for pl in plans:
                    pl_id = pl.get("id")
                    status = (pl.get("status") or "").upper()
                    interval_unit = None
                    interval_count = None
                    price_val = None
                    price_cur = None
                    try:
                        gp = pp_client.get_plan(pl_id)
                        if gp.get("ok"):
                            full = (gp.get("data") or {})
                            status = (full.get("status") or status).upper()
                            for cyc in (full.get("billing_cycles") or []):
                                if (cyc.get("tenure_type") or "").upper() == "REGULAR":
                                    freq = cyc.get("frequency") or {}
                                    interval_unit = freq.get("interval_unit")
                                    interval_count = freq.get("interval_count")
                                    fp = (cyc.get("pricing_scheme") or {}).get("fixed_price") or {}
                                    price_val = fp.get("value")
                                    price_cur = fp.get("currency_code")
                                    break
                    except Exception:
                        pass

                    try:
                        price_num = float(price_val) if price_val is not None else float("inf")
                    except Exception:
                        price_num = float("inf")
                    is_inactive = 1 if status != "ACTIVE" else 0
                    candidate = {
                        "id": pid,
                        "name": name,
                        "description": description,
                        "price": str(price_val) if price_val is not None else None,
                        "currency": (price_cur or "").upper() if price_cur else None,
                        "plan_id": pl_id,
                        "plan_interval": interval_unit,
                        "plan_interval_count": interval_count,
                    }
                    key = (is_inactive, price_num)
                    if best is None or key < best[:2]:
                        best = (is_inactive, price_num, candidate)

                return best[2] if best else {
                    "id": pid,
                    "name": name,
                    "description": description,
                    "price": None,
                    "currency": None,
                    "plan_id": None,
                    "plan_interval": None,
                    "plan_interval_count": None,
                }

            new_base: List[dict] = []
            max_workers = min(12, max(4, len(products)))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_build_row, p) for p in products]
                for f in as_completed(futures):
                    try:
                        new_base.append(f.result())
                    except Exception:
                        # Shouldn't happen often; skip on failure
                        pass

            _MENU_CACHE["data"] = new_base
            _MENU_CACHE["cached_at"] = now
            base = new_base

        # Apply search + limit on cached base
        def _norm(s: str) -> str:
            import re
            return re.sub(r"[^a-z0-9\s]", "", (s or "").lower()).strip()

        def _words(s: str) -> set[str]:
            # simple tokenizer + singularize trailing 's'
            w = [_w[:-1] if len(_w) > 3 and _w.endswith("s") else _w for _w in _norm(s).split() if _w]
            return set(w)

        def _match(nm: str) -> bool:
            if not query:
                return True
            q = _norm(query)
            name = _norm(nm)
            if exact:
                return name == q
            if q in name:
                return True
            try:
                # token overlap fallback (handles plurals like burgers -> burger)
                qw = _words(query)
                nw = _words(nm)
                if qw and nw and qw.intersection(nw):
                    return True
                from difflib import SequenceMatcher
                return SequenceMatcher(None, name, q).ratio() >= 0.5
            except Exception:
                return False

        result = [row for row in (base or []) if _match(row.get("name") or "")]
        if limit and len(result) > int(limit):
            result = result[: int(limit)]
        return result
    except Exception as e:
        logger.exception("get_menu_with_prices failed: %s", e)
        return []


def get_response(user_message, user_lower, history):
    """Chat with LLM exposing a single tool: menu listing with prices (with search).

    Tool: menu
    - query: optional string to search
    - exact: optional boolean for exact match
    - limit: optional integer to cap results
    """
    if client is None:
        return "Hi! LLM is not configured. Please set OPENAI_API_KEY."

    tools = [
        {
            "type": "function",
            "function": {
                "name": "menu",
                "description": "List menu items (PayPal products) with best plan prices. Supports search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "exact": {"type": "boolean"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "required": []
                },
            },
        },
    ]

    def _call_tool(name: str, arguments: dict) -> str:
        try:
            if name == "menu":
                items = get_menu_with_prices(
                    query=arguments.get("query"),
                    exact=bool(arguments.get("exact", False)),
                    limit=arguments.get("limit"),
                )
                return json.dumps({"items": items})
        except Exception as e:
            logger.exception("tool error: %s", e)
            return json.dumps({"error": str(e)})
        return json.dumps({"error": f"unknown tool {name}"})

    sys_prompt = (
        "You are a helpful assistant at an American cafe."
        " Help users decide what to order based on our live menu and prices."
        " Always call the 'menu' tool before asserting availability of any item or category."
        " For broad or semantic requests (e.g., 'anything sweet', 'a drink', 'something spicy', 'vegetarian'),"
        " first call the tool WITHOUT a query to fetch the full menu, then infer relevant items by reading names and descriptions."
        " If a filtered tool call returns zero items, call the tool again with NO filter and reason over the results before claiming unavailability."
        " Prefer clear, friendly, concise answers with item names, short descriptions, and prices (currency)."
        " When listing, show the top 3–5 most relevant items unless the user asks for more."
    )

    msgs = [{"role": "system", "content": sys_prompt}]

    # Include recent history as context
    try:
        for role, text in history[-6:]:
            role_norm = "user" if str(role).lower().startswith("you") else "assistant"
            msgs.append({"role": role_norm, "content": str(text)})
    except Exception:
        pass

    msgs.append({"role": "user", "content": user_message})

    # Tool loop
    for _ in range(3):
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=msgs,
            tools=tools,
            tool_choice="auto",
            temperature=OPENAI_TEMPERATURE,
            max_tokens=800,
        )
        msg = resp.choices[0].message
        if getattr(msg, "tool_calls", None):
            msgs.append({"role": "assistant", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                for tc in msg.tool_calls
            ]})
            for tc in msg.tool_calls:
                try:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    name, args = "", {}
                tool_result = _call_tool(name, args)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})
            continue
        content = msg.content or ""
        return content.strip() or "Got it."
    return "Sorry, I'm having trouble processing your request right now."
