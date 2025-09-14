# chatbot/nlp_utils.py
import json
import logging
import os
from typing import Any, Dict

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
    dashes = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
    return name.translate(str.maketrans({c: '-' for c in dashes})).strip()


OPENAI_MODEL = _normalize_model_name((os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip())
try:
    OPENAI_TEMPERATURE = float((os.getenv("OPENAI_TEMPERATURE") or "0.3").strip() or 0.3)
except ValueError:
    OPENAI_TEMPERATURE = 0.3

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# PayPal client (Sandbox/Live determined by settings)
pp_client = PayPalClient()


def _list_all_menu_items(query: str | None = None, limit: int | None = None) -> list[dict]:
    """Return simplified list of invoicing catalog items with pricing."""
    try:
        res = pp_client.list_all_invoicing_items()
        if not res.get("ok"):
            return []
        items = res.get("data", {}).get("items", [])
        out = []
        q = (query or "").lower().strip()
        for it in items:
            name = (it.get("name") or "").strip()
            if q and q not in name.lower():
                continue
            amt = it.get("unit_amount") or {}
            out.append({
                "id": it.get("id"),
                "name": name,
                "description": it.get("description") or "",
                "price": str(amt.get("value")) if amt.get("value") is not None else None,
                "currency": (amt.get("currency_code") or "USD").upper() if amt else None,
            })
            if limit and len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _search_items(term: str, exact: bool = False) -> list[dict]:
    matches = pp_client.search_items_by_name(term, exact_match=bool(exact))
    out = []
    # Build a price map to attach pricing
    try:
        all_items = _list_all_menu_items()
        price_by_id = {x["id"]: (x["price"], x["currency"]) for x in all_items if x.get("id")}
    except Exception:
        price_by_id = {}
    for m in matches or []:
        mid = m.get("id")
        pr_val, pr_cur = price_by_id.get(mid, (None, None))
        out.append({
            "id": mid,
            "name": (m.get("name") or "").strip(),
            "price": pr_val,
            "currency": pr_cur,
        })
    return out


def _get_pricing(id: str | None = None, name: str | None = None) -> Dict[str, Any]:
    items = _list_all_menu_items()
    if id:
        for it in items:
            if it.get("id") == id:
                return {"match_type": "id", "items": [it]}
        return {"match_type": "id", "items": []}
    if name:
        name_l = name.lower().strip()
        matches = []
        for it in items:
            nm = (it.get("name") or "").lower().strip()
            if nm == name_l or name_l in nm or nm in name_l:
                matches.append(it)
        return {"match_type": "name", "items": matches}
    return {"match_type": "none", "items": []}


def get_response(user_message, user_lower, history):
    """Chat with LLM and allow tool calls to query PayPal catalog and prices."""
    if client is None:
        return "Hi! LLM is not configured. Please set OPENAI_API_KEY."

    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_products",
                "description": "List available menu items from PayPal invoicing catalog. Optionally filter by a query substring.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Optional case-insensitive name contains filter."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100}
                    },
                    "required": []
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_all_products",
                "description": "List all menu items with prices (alias to list_products without filter).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200}
                    },
                    "required": []
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_items_by_name",
                "description": "Search items by name with fuzzy matching and include price when available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string"},
                        "exact": {"type": "boolean"}
                    },
                    "required": ["term"]
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_item_suggestions",
                "description": "Suggest item names based on overlap with item words.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string"},
                        "max": {"type": "integer", "minimum": 1, "maximum": 20}
                    },
                    "required": ["term"]
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_product_pricing",
                "description": "Get price and currency for an item by id or by name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"}
                    },
                    "required": []
                },
            },
        },
    ]

    def _call_tool(name: str, arguments: dict) -> str:
        try:
            if name == "list_products":
                items = _list_all_menu_items(arguments.get("query"), arguments.get("limit"))
                return json.dumps({"items": items})
            if name == "list_all_products":
                items = _list_all_menu_items(limit=arguments.get("limit"))
                return json.dumps({"items": items})
            if name == "search_items_by_name":
                term = arguments.get("term") or ""
                exact = bool(arguments.get("exact", False))
                items = _search_items(term, exact=exact)
                return json.dumps({"items": items})
            if name == "get_item_suggestions":
                term = arguments.get("term") or ""
                mx = int(arguments.get("max", 8))
                suggests = pp_client.get_item_suggestions(term, max_suggestions=mx)
                return json.dumps({"suggestions": suggests})
            if name == "get_product_pricing":
                return json.dumps(_get_pricing(arguments.get("id"), arguments.get("name")))
        except Exception as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"error": f"unknown tool {name}"})

    sys_prompt = (
        "You are a helpful food-ordering assistant."
        " Use the provided tools to look up the live menu and prices from PayPal invoicing catalog."
        " Be concise and friendly."
        " If the user wants to order something, confirm the item and quantity and ask for their email to send a PayPal payment link."
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
            # Execute each tool call and append its result
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
        # No tool calls – return text
        content = msg.content or ""
        return content.strip() or "Got it."
    return "Sorry, I'm having trouble processing your request right now."
