# chatbot/views.py
from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json
import logging
from django.shortcuts import render

from payments.models import ProductPrice
from payments.paypal_api import PayPalClient
from .nlp_utils import analyze_user_intent

logger = logging.getLogger(__name__)
paypal_client = PayPalClient()

@method_decorator(csrf_exempt, name='dispatch')
class ChatbotAPI(View):
    def post(self, request):
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
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

        if intent == "list_products":
            # Use new method to get ALL products
            result = paypal_client.list_all_products()
            if result.get("ok"):
                products_data = result.get("data", {})
                all_products = products_data.get("products", [])
                pages_fetched = products_data.get("pages_fetched", 0)
                
                if all_products:
                    # Get local prices
                    local_prices = {p.product_id: p for p in ProductPrice.objects.all()}
                    
                    product_list = []
                    for product in all_products:
                        product_id = product["id"]
                        product_name_display = product["name"]
                        
                        if product_id in local_prices:
                            price_info = local_prices[product_id]
                            product_list.append(f"• {product_name_display}: {price_info.price} {price_info.currency}")
                        else:
                            product_list.append(f"• {product_name_display}: Price not set")
                    
                    reply = f"📋 Found {len(all_products)} products (searched {pages_fetched} pages):\n" + "\n".join(product_list)
                else:
                    reply = "No products found in your PayPal account."
            else:
                reply = f"Error fetching products: {result.get('error', 'Unknown error')}"
        
        elif intent == "pizza_types":
            # Handle pizza types/menu requests (show all pizzas)
            result = paypal_client.list_all_products()
            if result.get("ok"):
                products_data = result.get("data", {})
                all_products = products_data.get("products", [])
                
                # Get local prices first
                local_prices = {p.product_id: p for p in ProductPrice.objects.all()}
                
                # Filter pizza products that have prices set
                pizza_products_with_prices = []
                for product in all_products:
                    product_name_lower = product["name"].lower()
                    product_id = product["id"]
                    
                    # Only include pizzas that have prices set
                    if "pizza" in product_name_lower and product_id in local_prices:
                        pizza_products_with_prices.append(product)
                
                if pizza_products_with_prices:
                    pizza_list = []
                    for product in pizza_products_with_prices:
                        product_name_display = product["name"]
                        pizza_list.append(f"• {product_name_display}")
                    
                    reply = f"🍕 Available Pizza Types ({len(pizza_products_with_prices)} found):\n" + "\n".join(pizza_list)
                else:
                    reply = "🍕 No pizza products with prices set found in your catalog."
            else:
                reply = f"Error fetching products: {result.get('error', 'Unknown error')}"

        elif product_name:
            # Handle specific product queries (including specific pizza price queries)
            matching_products = paypal_client.search_products_by_name(product_name)
            
            logger.debug(f"Matched PayPal products: {len(matching_products)}")
            print(f"Matched PayPal products: {len(matching_products)}")

            if matching_products:
                # Check if user asked for generic "pizza" and we found multiple pizza results
                if (product_name.lower() == "pizza" and 
                    len(matching_products) > 1 and 
                    all("pizza" in p["name"].lower() for p in matching_products)):
                    
                    # Generic pizza query with multiple results - show all pizzas with prices
                    local_prices = {p.product_id: p for p in ProductPrice.objects.all()}
                    pizza_with_prices = [p for p in matching_products if p["id"] in local_prices]
                    
                    if pizza_with_prices:
                        pizza_list = []
                        for product in pizza_with_prices:
                            product_id = product["id"]
                            product_name_display = product["name"]
                            price_info = local_prices[product_id]
                            pizza_list.append(f"• {product_name_display}: {price_info.price} {price_info.currency}")
                        
                        if intent == "price_query":
                            reply = f"🍕 All Pizza Prices:\n" + "\n".join(pizza_list)
                        else:
                            reply = f"🍕 Found {len(pizza_with_prices)} Pizza Types with Prices:\n" + "\n".join(pizza_list)
                    else:
                        reply = "🍕 No pizza products with prices set found."
                else:
                    # Handle specific product (including specific pizza like "margherita pizza")
                    matched_product = matching_products[0]
                    product_id = matched_product["id"]

                    if intent == "price_query":
                        # Fetch price from local DB for specific product
                        try:
                            product = ProductPrice.objects.get(product_id=product_id)
                            reply = f"💰 {matched_product['name']}: {product.price} {product.currency}"
                            
                            # Mention if there are other similar products
                            if len(matching_products) > 1:
                                reply += f"\n\n(Found {len(matching_products)} similar products)"
                                
                        except ProductPrice.DoesNotExist:
                            reply = f"Product '{matched_product['name']}' exists on PayPal but price is not set locally."
                                
                    elif intent == "product_info":
                        # Show conversational product information using description
                        product_description = matched_product.get('description', '')
                        
                        if product_description:
                            # Use the description to provide conversational response
                            reply = f"🍕 **{matched_product['name']}**\n\n{product_description}"
                            
                            # Add price if available
                            try:
                                product = ProductPrice.objects.get(product_id=product_id)
                                reply += f"\n\n💰 **Price:** {product.price} {product.currency}"
                            except ProductPrice.DoesNotExist:
                                reply += f"\n\n💰 **Price:** Not set locally"
                        else:
                            # Fallback if no description available
                            reply = f"ℹ️ **{matched_product['name']}**\n\nSorry, I don't have detailed information about this product right now."
                            
                            # Still show price if available
                            try:
                                product = ProductPrice.objects.get(product_id=product_id)
                                reply += f"\n\n💰 **Price:** {product.price} {product.currency}"
                            except ProductPrice.DoesNotExist:
                                reply += f"\n\n💰 **Price:** Not set locally"
                        
                        # Mention if there are other similar products
                        if len(matching_products) > 1:
                            reply += f"\n\n*Found {len(matching_products)} similar products. Try asking about specific ones!*"
                    else:
                        reply = f"✅ Product '{matched_product['name']}' is available."
                        
                        if len(matching_products) > 1:
                            reply += f"\n\n(Found {len(matching_products)} similar products)"
            else:
                # Get suggestions if no exact match
                suggestions = paypal_client.get_product_suggestions(product_name, max_suggestions=3)
                
                if suggestions:
                    reply = f"No exact match for '{product_name}'. Did you mean: {', '.join(suggestions)}?"
                else:
                    # Show total products searched
                    result = paypal_client.list_all_products()
                    if result.get("ok"):
                        total_products = result.get("data", {}).get("total_items", 0)
                        reply = f"No product found with name '{product_name}'. Searched {total_products} total products."
                    else:
                        reply = f"No product found with name '{product_name}'."

        logger.debug(f"Reply to user: {reply}")
        print(f"Reply to user: {reply}")

        return JsonResponse({"reply": reply})
    

class ChatbotUI(View):
    """Class-based view to render the chatbot frontend page."""
    template_name = "ChatbotUi/ChatbotUi.html"

    def get(self, request):
        return render(request, self.template_name)