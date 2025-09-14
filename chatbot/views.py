# chatbot/views.py
from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json
import logging
from django.shortcuts import render

from paypal_project.paypal_api import PayPalClient
from .nlp_utils import analyze_user_intent

logger = logging.getLogger(__name__)
paypal_client = PayPalClient()

@method_decorator(csrf_exempt, name='dispatch')
class ChatbotAPI(View):
    def post(self, request):
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
        user_lower = user_message.lower()
        history = data.get("history", [])  # Optional: [["You", "text"], ["Bot", "text"], ...]
        logger.debug(f"User message received: {user_message}")
        print(f"User message received: {user_message}")

        # Analyze intent using NLP
        nlp_result = analyze_user_intent(user_message)
        logger.debug(f"NLP result: {nlp_result}")
        print(f"NLP result: {nlp_result}")

        intent = nlp_result.get("intent")          # "price_query", "list_products", "pizza_types", "product_info", "other"
        product_name = nlp_result.get("product_name")  # Extracted product name
        category = nlp_result.get("category")      # Product category like "pizza"

        reply = "Sorry, I didn't understand that."

        # Lightweight conversation memory for follow-ups
        last_product = request.session.get("last_product")  # {"id": str, "name": str}
        last_category = request.session.get("last_category")  # e.g., 'pizza', 'burrito'
        awaiting_email = request.session.get("awaiting_email")
        pending_invoice_items = request.session.get("pending_invoice_items")  # list of {id,name,quantity}

        # Minimal order flow: capture email and create/send PayPal invoice
        import re
        EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

        if awaiting_email:
            m = EMAIL_RE.search(user_message)
            if m:
                email = m.group(0)
                # Build line items from pending item ids
                items, price_by_id = [], {}
                menu, price_by_id = (lambda: (paypal_client.list_all_invoicing_items().get('data',{}).get('items',[]), {}))()
                # Rebuild the price map
                pb = {}
                for it in menu:
                    uid = it.get('id')
                    amt = it.get('unit_amount') or {}
                    if uid and amt.get('value'):
                        pb[uid] = (str(amt.get('value')), (amt.get('currency_code') or 'USD').upper(), it.get('name'))
                line_items = []
                for sel in pending_invoice_items or []:
                    pid = sel.get('id')
                    qty = str(sel.get('quantity', 1))
                    if pid in pb:
                        val, cur, nm = pb[pid]
                        line_items.append({
                            'name': nm or sel.get('name') or 'Item',
                            'quantity': qty,
                            'unit_amount': {'currency_code': cur, 'value': str(val)},
                        })
                if not line_items:
                    request.session['awaiting_email'] = False
                    request.session['pending_invoice_items'] = []
                    request.session.modified = True
                    return JsonResponse({"reply": "Sorry, I lost the cart context. Please say 'order <item name>' again."})

                # Create and send invoice
                inv = paypal_client.create_and_send_invoice(email, line_items, currency='USD')
                request.session['awaiting_email'] = False
                request.session['pending_invoice_items'] = []
                request.session.modified = True
                if inv.get('ok'):
                    return JsonResponse({"reply": f"✅ Order successful. A PayPal payment link was emailed to {email}."})
                else:
                    return JsonResponse({"reply": f"❌ Could not create invoice: {inv.get('error','unknown error')}"})
            else:
                return JsonResponse({"reply": "Please enter a valid email id to receive the payment link."})

        def infer_category_emoji(text: str | None):
            n = (text or "").lower()
            if "pizza" in n:
                return "pizza", "🍕"
            if "burrito" in n or "burito" in n:
                return "burrito", "🌯"
            if "burger" in n or "cheeseburger" in n:
                return "burger", "🍔"
            if "sandwich" in n or "hoagie" in n:
                return "sandwich", "🥪"
            if "salad" in n or "caesar" in n:
                return "salad", "🥗"
            if any(k in n for k in ["fries", "onion rings", "side", "coleslaw", "slaw"]):
                return "side", "🍟"
            if any(k in n for k in ["drink", "soda", "lemonade", "milkshake", "iced tea", "tea"]):
                return "drink", "🥤"
            if any(k in n for k in ["dessert", "brownie", "cheesecake", "pie", "sundae", "cake", "ice cream"]):
                return "dessert", "🍰"
            return None, "•"

        # Load menu + prices from PayPal Invoicing catalog
        def _load_menu_and_prices():
            res = paypal_client.list_all_invoicing_items()
            if not res.get("ok"):
                return [], {}
            items = res.get("data", {}).get("items", [])
            price_by_id = {}
            for it in items:
                iid = it.get("id")
                amt = it.get("unit_amount") or {}
                if iid and amt.get("value"):
                    price_by_id[iid] = (str(amt.get("value")), (amt.get("currency_code") or "USD").upper())
            return items, price_by_id

        def build_category_recommendations(cat_key: str, title_prefix: str = "More"):
            if not cat_key:
                return None
            prods, price_by_id = _load_menu_and_prices()
            if not prods:
                return None
            priced_lines, unpriced = [], []
            for p in prods:
                cat, _ = infer_category_emoji(p.get("name"))
                if cat == cat_key:
                    pid = p.get("id")
                    name = p.get("name") or ""
                    if pid in price_by_id:
                        val, cur = price_by_id[pid]
                        priced_lines.append(f"• {name}: {val} {cur}")
                    else:
                        unpriced.append(f"• {name}")
            lines = sorted(priced_lines)[:5]
            if len(lines) < 5:
                lines += sorted(unpriced)[: 5 - len(lines)]
            if not lines:
                return None
            title = f"{title_prefix} {cat_key.title()}s:" if not cat_key.endswith("s") else f"{title_prefix} {cat_key.title()}:"
            return title + "\n" + "\n".join(lines)

        # Friendly small-talk handler
        greet_triggers = ("hello", "hi", "hey", "good morning", "good evening", "how are you")
        if (not intent or intent == "other") and any(k in user_lower for k in greet_triggers):
            reply = (
                "Hi! I can help you browse products and prices. "
                "Try 'show pizza menu', 'price of Margherita Pizza', or 'do you have burrito?'."
            )
            logger.debug(f"Reply to user: {reply}")
            print(f"Reply to user: {reply}")
            return JsonResponse({"reply": reply})

        # If user asks about price without specifying a product, try using last context
        price_triggers = ("price", "cost", "how much", "how much is it", "how much is that")
        if (not intent or intent == "other") and any(k in user_lower for k in price_triggers):
            if not product_name:
                # Prefer FE-provided history to infer prior product
                prev_user_text = None
                you_seen = 0
                for speaker, text in reversed(history):
                    if speaker.lower().startswith("you"):
                        you_seen += 1
                        if you_seen == 1:
                            # current message
                            continue
                        if you_seen == 2:
                            prev_user_text = text
                            break
                inferred_product_name = None
                if prev_user_text:
                    matches = paypal_client.search_products_by_name(prev_user_text)
                    if matches:
                        inferred_product_name = matches[0]["name"]
                        # Also cache for future
                        request.session["last_product"] = {"id": matches[0]["id"], "name": matches[0]["name"]}
                        request.session.modified = True

                if last_product and not inferred_product_name:
                    inferred_product_name = last_product.get("name")

                if inferred_product_name:
                    intent = "price_query"
                    product_name = inferred_product_name

        # Minimal order detection: user wants to place an order
        order_triggers = ("order", "buy", "checkout")
        if any(k in user_lower for k in order_triggers):
            # Try to resolve a product from the message
            target_name = product_name or user_message
            matches = paypal_client.search_items_by_name(target_name)
            if not matches:
                return JsonResponse({"reply": "I couldn't find that item. Try 'order Margherita Pizza'."})
            if len(matches) > 1:
                # Ask to clarify
                names = []
                seen = set()
                for m in matches:
                    nm = (m.get('name') or '').strip()
                    if nm and nm.lower() not in seen:
                        names.append(f"• {nm}")
                        seen.add(nm.lower())
                    if len(names) >= 5:
                        break
                return JsonResponse({"reply": "Which one would you like to order?\n" + "\n".join(names)})
            # Single match – set pending cart and ask for email
            sel = matches[0]
            request.session['pending_invoice_items'] = [{
                'id': sel.get('id'),
                'name': sel.get('name'),
                'quantity': 1,
            }]
            request.session['awaiting_email'] = True
            request.session.modified = True
            return JsonResponse({"reply": "Great! Please enter email id to receive the payment link."})

        # If the model returned 'other', try to infer a category from the message/history
        if (not intent or intent == "other"):
            # From current message
            cat_msg = None
            for probe in (user_message,):
                # reuse the emoji helper to infer category
                cat_msg, _ = (infer_category_emoji(probe) if 'infer_category_emoji' in locals() or 'infer_category_emoji' in globals() else (None, '•'))
                if cat_msg:
                    break
            # From previous user turn in history
            if not cat_msg and history:
                prev_user = None
                you_seen = 0
                for speaker, text in reversed(history):
                    if speaker.lower().startswith("you"):
                        you_seen += 1
                        if you_seen == 1:
                            continue
                        prev_user = text
                        break
                if prev_user:
                    cat_prev, _ = (infer_category_emoji(prev_user) if 'infer_category_emoji' in locals() or 'infer_category_emoji' in globals() else (None, '•'))
                    if cat_prev:
                        cat_msg = cat_prev
            if cat_msg:
                intent = "list_products"
                category = cat_msg
                request.session["last_category"] = cat_msg
                request.session.modified = True

        # Map list_products with pizza hints to pizza_types for better UX
        if intent == "list_products" and (
            (product_name and product_name.lower() == "pizza") or
            (category and str(category).lower() == "pizza") or
            ("pizza" in user_lower)
        ):
            intent = "pizza_types"
            # Remember last category for follow-ups
            request.session["last_category"] = "pizza"
            request.session.modified = True

        # Handle "options/choices/suggest" follow-ups by inferring context from history
        option_triggers = ("options", "choices", "what are the options", "what options", "what are my options",
                           "what else", "anything else", "something else", "recommend", "suggest")
        if (not intent or intent in ("other", "suggest")) and any(k in user_lower for k in option_triggers):
            prev_user_text = None
            you_seen = 0
            for speaker, text in reversed(history):
                if speaker.lower().startswith("you"):
                    you_seen += 1
                    if you_seen == 1:
                        continue
                    if you_seen == 2:
                        prev_user_text = text
                        break
            if prev_user_text and "pizza" in prev_user_text.lower():
                intent = "pizza_types"
            elif prev_user_text:
                matches = paypal_client.search_items_by_name(prev_user_text)
                if matches:
                    _items, price_by_id = _load_menu_and_prices()
                    lines = []
                    shown = set()
                    for m in matches:
                        name = m.get("name", "").strip()
                        pid = m.get("id")
                        if not name or name in shown:
                            continue
                        shown.add(name)
                        if pid in price_by_id:
                            val, cur = price_by_id[pid]
                            lines.append(f"• {name}: {val} {cur}")
                        else:
                            lines.append(f"• {name}")
                        if len(lines) >= 8:
                            break
                    if lines:
                        reply = "Here are some options:\n" + "\n".join(lines)
                        logger.debug(f"Reply to user: {reply}")
                        print(f"Reply to user: {reply}")
                        return JsonResponse({"reply": reply})
            # If we have a last_category, recommend from it
            if last_category:
                block = build_category_recommendations(last_category, title_prefix="More")
                if block:
                    reply = block
                    logger.debug(f"Reply to user: {reply}")
                    print(f"Reply to user: {reply}")
                    return JsonResponse({"reply": reply})
            # If no context found, fall through to normal handlers

        if intent in ("list_products", "suggest"):
            # Use invoicing catalog items as the source of truth
            result = paypal_client.list_all_invoicing_items()
            if result.get("ok"):
                products_data = result.get("data", {})
                all_products = products_data.get("items", [])
                if not all_products:
                    reply = "No menu items found in PayPal."
                else:
                    # Build price map
                    price_by_id = {}
                    for it in all_products:
                        uid = it.get("id")
                        amt = it.get("unit_amount") or {}
                        if uid and amt.get("value"):
                            price_by_id[uid] = (str(amt.get("value")), (amt.get("currency_code") or "USD").upper())

                    # Generic filtering driven by LLM-provided search_terms/category
                    search_terms = nlp_result.get("search_terms") or []
                    if not isinstance(search_terms, list):
                        search_terms = []
                    search_terms = [str(t).lower().strip() for t in search_terms if str(t).strip()]
                    if not search_terms and category:
                        search_terms = [str(category).lower().strip()]
                    if not search_terms:
                        import re
                        stop = {"do","you","have","a","an","the","any","please","me","some","item","items","view","show","all","options","what","are","is","there","available","of","for"}
                        tokens = [t for t in re.split(r"[^a-zA-Z]+", user_lower) if t]
                        terms = [t for t in tokens if t not in stop and len(t) > 1]
                        search_terms = terms[:4]

                    def matches_terms(name: str) -> bool:
                        n = (name or "").lower()
                        if not search_terms:
                            return True
                        return any(term in n for term in search_terms)

                    filtered_priced = []
                    filtered_unpriced = []
                    for p in all_products:
                        name = p.get("name", "")
                        if not matches_terms(name):
                            continue
                        pid = p.get("id")
                        if pid in price_by_id:
                            pr_val, pr_cur = price_by_id[pid]
                            filtered_priced.append((name, str(pr_val), pr_cur))
                        else:
                            filtered_unpriced.append(name)
                    filtered_priced.sort(key=lambda t: t[0])
                    filtered_unpriced.sort()

                    def render_block(title: str) -> str:
                        total = len(filtered_priced) + len(filtered_unpriced)
                        if total == 0:
                            return f"No items found for {title}."
                        lines = [f"• {n}: {p} {c}" for n, p, c in filtered_priced[:8]]
                        remaining = max(0, 8 - len(lines))
                        if remaining > 0:
                            lines += [f"• {n}" for n in filtered_unpriced[:remaining]]
                        more = total - len(lines)
                        more_line = f"\n… +{more} more" if more > 0 else ""
                        return f"{title} ({total}):\n" + "\n".join(lines) + more_line

                    title = "Recommendations" if intent == "suggest" else ("Menu" if not search_terms else f"Menu for: {', '.join(search_terms)}")
                    total_matches = len(filtered_priced) + len(filtered_unpriced)
                    if total_matches == 0:
                        # Try suggestions based on the user's query
                        query_str = None
                        if product_name:
                            query_str = str(product_name)
                        elif search_terms:
                            query_str = " ".join(search_terms)
                        else:
                            query_str = user_message

                        suggestions = []
                        if query_str:
                            try:
                                suggestions = paypal_client.get_item_suggestions(query_str, max_suggestions=8)
                            except Exception:
                                suggestions = []

                        if suggestions:
                            # Map suggestion names back to products to attach prices when available
                            name_to_product = { (p.get("name") or "").strip().lower(): p for p in all_products }
                            lines = []
                            for s in suggestions:
                                s_key = (s or "").strip().lower()
                                prod = name_to_product.get(s_key)
                                if not prod:
                                    lines.append(f"• {s}")
                                    continue
                                pid = prod.get("id")
                                if pid in price_by_id:
                                    pr_val, pr_cur = price_by_id[pid]
                                    lines.append(f"• {s}: {pr_val} {pr_cur}")
                                else:
                                    lines.append(f"• {s}")
                            reply = f"I couldn't find '{query_str}'. Here are some similar items:\n" + "\n".join(lines)
                        else:
                            # Fallback: show a handful of priced items as alternatives
                            priced_all = []
                            for p in all_products:
                                pid = p.get("id")
                                if pid in price_by_id:
                                    pr_val, pr_cur = price_by_id[pid]
                                    priced_all.append(((p.get("name") or ""), str(pr_val), pr_cur))
                            priced_all.sort(key=lambda t: t[0])
                            lines = [f"• {n}: {p} {c}" for n, p, c in priced_all[:8]] or ["• Browse the menu to see options"]
                            reply = f"I couldn't find '{query_str}'. Here are some popular items:\n" + "\n".join(lines)
                    else:
                        reply = render_block(title)
            else:
                reply = f"Error fetching items: {result.get('error', 'Unknown error')}"
        
        elif intent == "pizza_types":
            # Handle pizza types/menu requests (show all pizzas)
            result = paypal_client.list_all_invoicing_items()
            if result.get("ok"):
                products_data = result.get("data", {})
                all_products = products_data.get("items", [])

                # Build price map
                price_by_id = {}
                for it in all_products:
                    uid = it.get("id")
                    amt = it.get("unit_amount") or {}
                    if uid and amt.get("value"):
                        price_by_id[uid] = (str(amt.get("value")), (amt.get("currency_code") or "USD").upper())

                pizza_with_prices = []
                unpriced_pizza = 0
                for product in all_products:
                    name_lower = product.get("name", "").lower()
                    pid = product.get("id")
                    if "pizza" in name_lower:
                        if pid in price_by_id:
                            pr_val, pr_cur = price_by_id[pid]
                            pizza_with_prices.append((product.get("name", ""), str(pr_val), pr_cur))
                        else:
                            unpriced_pizza += 1

                if pizza_with_prices:
                    pizza_with_prices.sort(key=lambda t: t[0])
                    lines = [f"• {n}: {p} {c}" for n, p, c in pizza_with_prices]
                    tail_note = f"\n… +{unpriced_pizza} more" if unpriced_pizza else ""
                    reply = f"🍕 Pizza Menu ({len(pizza_with_prices) + unpriced_pizza}):\n" + "\n".join(lines) + tail_note
                else:
                    if unpriced_pizza:
                        reply = f"🍕 Pizza Menu ({unpriced_pizza}):\n" + "\n".join(["• " + p.get("name","") for p in all_products if "pizza" in (p.get("name"," ").lower())])
                    else:
                        reply = "🍕 No pizza products found."
            else:
                reply = f"Error fetching items: {result.get('error', 'Unknown error')}"

        elif product_name:
            # Handle specific product queries (including specific pizza price queries)
            matching_products = paypal_client.search_items_by_name(product_name)
            
            logger.debug(f"Matched PayPal products: {len(matching_products)}")
            print(f"Matched PayPal products: {len(matching_products)}")

            if matching_products:
                # Check if user asked for generic "pizza" and we found multiple pizza results
                if (product_name.lower() == "pizza" and 
                    len(matching_products) > 1 and 
                    all("pizza" in p["name"].lower() for p in matching_products)):
                    # Generic pizza query with multiple results - show all pizzas with prices
                    _all, price_by_id = _load_menu_and_prices()
                    pizza_with_prices = [p for p in matching_products if p.get("id") in price_by_id]
                    if pizza_with_prices:
                        pizza_list = []
                        for product in pizza_with_prices:
                            product_id = product.get("id")
                            product_name_display = product.get("name")
                            pr_val, pr_cur = price_by_id[product_id]
                            pizza_list.append(f"• {product_name_display}: {pr_val} {pr_cur}")
                        if intent == "price_query":
                            reply = f"🍕 All Pizza Prices:\n" + "\n".join(pizza_list)
                        else:
                            reply = f"🍕 Found {len(pizza_with_prices)} Pizza Types with Prices:\n" + "\n".join(pizza_list)
                    else:
                        reply = "🍕 No pizza products with prices available."
                else:
                    # Handle specific product (including specific pizza like "margherita pizza")
                    matched_product = matching_products[0]
                    product_id = matched_product["id"]
                    # Store context for follow-ups
                    request.session["last_product"] = {"id": product_id, "name": matched_product["name"]}
                    cat_key, emj = infer_category_emoji(matched_product.get("name"))
                    if cat_key:
                        request.session["last_category"] = cat_key
                    request.session.modified = True

                    if intent == "price_query":
                        # Price from invoicing items
                        _all, price_by_id = _load_menu_and_prices()
                        _cat, emj = infer_category_emoji(matched_product['name'])
                        if product_id in price_by_id:
                            pr_val, pr_cur = price_by_id[product_id]
                            reply = f"{emj} {matched_product['name']}\n\n💰 Price: {pr_val} {pr_cur}"
                            if len(matching_products) > 1:
                                reply += f"\n\n(Found {len(matching_products)} similar products)"
                        else:
                            alt = build_category_recommendations(_cat or last_category or "", title_prefix="Similar") if (_cat or last_category) else None
                            if alt:
                                reply = f"{emj} {matched_product['name']}\n\n💰 Price: Unavailable.\n\n{alt}"
                            else:
                                reply = f"{emj} {matched_product['name']}\n\n💰 Price: Unavailable."
                                
                    elif intent == "product_info":
                        # Show conversational product information using description
                        product_description = matched_product.get('description', '')
                        
                        if product_description:
                            # Use the description to provide conversational response
                            _cat, emj = infer_category_emoji(matched_product['name'])
                            reply = f"{emj} **{matched_product['name']}**\n\n{product_description}"
                            # Add price if available
                            _all, price_by_id = _load_menu_and_prices()
                            if product_id in price_by_id:
                                pr_val, pr_cur = price_by_id[product_id]
                                reply += f"\n\n💰 **Price:** {pr_val} {pr_cur}"
                            else:
                                alt = build_category_recommendations(_cat or last_category or "", title_prefix="Similar") if (_cat or last_category) else None
                                if alt:
                                    reply += f"\n\n💰 **Price:** Unavailable\n\n{alt}"
                                else:
                                    reply += f"\n\n💰 **Price:** Unavailable"
                        else:
                            # Fallback if no description available
                            _cat, emj = infer_category_emoji(matched_product['name'])
                            reply = f"ℹ️ **{matched_product['name']}**\n\nSorry, I don't have detailed information about this product right now."
                            # Still show price if available
                            _all, price_by_id = _load_menu_and_prices()
                            if product_id in price_by_id:
                                pr_val, pr_cur = price_by_id[product_id]
                                reply += f"\n\n💰 **Price:** {pr_val} {pr_cur}"
                            else:
                                alt = build_category_recommendations(_cat or last_category or "", title_prefix="Similar") if (_cat or last_category) else None
                                if alt:
                                    reply += f"\n\n💰 **Price:** Unavailable\n\n{alt}"
                                else:
                                    reply += f"\n\n💰 **Price:** Unavailable"
                        
                        # Mention if there are other similar products
                        if len(matching_products) > 1:
                            reply += f"\n\n*Found {len(matching_products)} similar products. Try asking about specific ones!*"
                    else:
                        # If multiple similar matches, show options instead of a generic line
                        if len(matching_products) > 1 and intent not in ("price_query", "product_info"):
                            _all, price_by_id = _load_menu_and_prices()
                            lines = []
                            shown = set()
                            for m in matching_products:
                                name = m.get("name", "").strip()
                                pid = m.get("id")
                                if not name or name in shown:
                                    continue
                                shown.add(name)
                                if pid in price_by_id:
                                    pr_val, pr_cur = price_by_id[pid]
                                    lines.append(f"• {name}: {pr_val} {pr_cur}")
                                else:
                                    lines.append(f"• {name}")
                                if len(lines) >= 8:
                                    break
                            reply = f"Found {len(matching_products)} options related to '{product_name}':\n" + "\n".join(lines)
                        else:
                            _cat, emj = infer_category_emoji(matched_product['name'])
                            reply = f"{emj} Product '{matched_product['name']}' is available."
            else:
                # Get suggestions if no exact match
                suggestions = paypal_client.get_item_suggestions(product_name, max_suggestions=3)
                
                if suggestions:
                    reply = f"No exact match for '{product_name}'. Did you mean: {', '.join(suggestions)}?"
                else:
                    # Show total products searched
                    result = paypal_client.list_all_invoicing_items()
                    if result.get("ok"):
                        total_products = result.get("data", {}).get("total_items", 0)
                        reply = f"No item found with name '{product_name}'. Searched {total_products} total items."
                    else:
                        reply = f"No item found with name '{product_name}'."

        # Handle price follow-up with context when no product name provided
        elif intent == "price_query" and not product_name:
            if last_product:
                _all, price_by_id = _load_menu_and_prices()
                pid = last_product.get("id") if isinstance(last_product, dict) else None
                if pid and pid in price_by_id:
                    pr_val, pr_cur = price_by_id[pid]
                    reply = f"💰 {last_product.get('name')}: {pr_val} {pr_cur}"
                else:
                    reply = f"Price for '{last_product.get('name')}' is not available."
            else:
                reply = "Which product are you asking the price for?"

        logger.debug(f"Reply to user: {reply}")
        print(f"Reply to user: {reply}")

        return JsonResponse({"reply": reply})
    

class ChatbotUI(View):
    """Class-based view to render the chatbot frontend page."""
    template_name = "ChatbotUi/ChatbotUi.html"

    def get(self, request):
        return render(request, self.template_name)
