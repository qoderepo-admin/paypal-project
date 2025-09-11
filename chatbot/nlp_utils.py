# chatbot/nlp_utils.py
import json
import re
import logging
import os
from openai import OpenAI

logger = logging.getLogger(__name__)

# Read the key from the environment; keep client construct lazy-friendly
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "")) 

def analyze_user_intent(message: str):
    """
    Analyze user message using OpenAI GPT to extract intent, product names, and category.
    Returns JSON like:
    {
      "intent": "price_query" or "list_products" or "pizza_types" or "product_info" or "other",
      "product_name": "<name or null>",
      "product_names": ["<name1>", "<name2>"] or null (for comparisons),
      "category": "<category like pizza, burger, etc. or null>"
    }
    """
    prompt = f"""
    You are a helpful assistant. Determine the user's intent, product names, and category.
    User message: "{message}"
    
    Respond ONLY in JSON format like:
    {{
        "intent": "price_query" or "list_products" or "pizza_types" or "product_info" or "other",
        "product_name": "<name or null>",
        "product_names": null,
        "category": "<category or null>"
    }}
    
    Intent guidelines:
    - "price_query": user asks for price of a specific product
    - "list_products": user wants to see all products/list/catalog
    - "pizza_types": user asks about different types of pizza, pizza varieties, or pizza menu
    - "product_info": user asks for information/description/details about a specific product
    - "other": any other request
    
    Product name guidelines:
    - For all queries: set "product_name" and leave "product_names" as null
    - Extract the exact product names mentioned
    - Return null if no specific product is mentioned
    - For general queries like "pizza" or "pizzas", set product_name to "pizza"
    
    Category guidelines:
    - Identify the food category (pizza, burger, drink, etc.)
    - Return null if no food category is mentioned
    - Common categories: pizza, burger, sandwich, drink, dessert, etc.
    
    Examples:
    - "what pizzas do you have" → intent: "pizza_types", product_name: null, product_names: null, category: "pizza"
    - "price of margherita pizza" → intent: "price_query", product_name: "margherita pizza", product_names: null, category: "pizza"
    - "tell me about supreme pizza" → intent: "product_info", product_name: "supreme pizza", product_names: null, category: "pizza"
    """

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts intent, product names, and categories from user messages. Always respond in valid JSON format."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0
        )

        output_text = response.choices[0].message.content.strip()
        logger.debug(f"NLP raw output: {output_text}")
        print(f"NLP raw output: {output_text}")

        # Remove ```json or ``` wrapping if present
        cleaned_text = re.sub(r"^```json\s*|```\s*$", "", output_text, flags=re.MULTILINE).strip()
        logger.debug(f"NLP cleaned output: {cleaned_text}")

        return json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        logger.error("JSON decode error in NLP: %s", e)
        print("JSON decode error in NLP:", e)
        # Fallback logic
        return fallback_intent_analysis(message)
    except Exception as e:
        logger.error("Error in NLP: %s", e)
        print("Error in NLP:", e)
        return fallback_intent_analysis(message)

def fallback_intent_analysis(message: str):
    """
    Enhanced fallback logic when OpenAI fails
    """
    message_lower = message.lower().strip()
    
    # Check for product information requests
    info_keywords = [
        'tell me about', 'what is', 'describe', 'description of', 'info about',
        'information about', 'details about', 'about', 'explain', 'tell me something about',
        'what\'s in', 'ingredients of', 'made of', 'contains'
    ]
    
    if any(keyword in message_lower for keyword in info_keywords):
        category = None
        product_name = None
        
        # Detect category
        if 'pizza' in message_lower:
            category = 'pizza'
        elif 'burger' in message_lower:
            category = 'burger'
        elif 'drink' in message_lower:
            category = 'drink'
        
        # Extract product name after info keywords
        for keyword in info_keywords:
            if keyword in message_lower:
                parts = message_lower.split(keyword)
                if len(parts) > 1:
                    potential_product = parts[1].strip()
                    # Clean up common words
                    potential_product = re.sub(r'\b(the|a|an)\b', '', potential_product).strip()
                    if potential_product:
                        product_name = potential_product.title()
                        break
        
        return {
            "intent": "product_info", 
            "product_name": product_name, 
            "product_names": None,
            "category": category
        }
    
    # Check for pizza type requests
    pizza_type_keywords = [
        'pizza types', 'types of pizza', 'pizza menu', 'pizza varieties', 
        'different pizzas', 'what pizzas', 'pizza options', 'available pizzas',
        'pizza flavors', 'pizza kinds'
    ]
    
    if any(keyword in message_lower for keyword in pizza_type_keywords):
        return {
            "intent": "pizza_types", 
            "product_name": None, 
            "product_names": None,
            "category": "pizza"
        }
    
    # Check for general list requests
    if any(word in message_lower for word in ['list', 'show all', 'all products', 'catalog', 'menu']):
        return {
            "intent": "list_products", 
            "product_name": None, 
            "product_names": None,
            "category": None
        }
    
    # Check for price queries
    price_keywords = ['price', 'cost', 'how much', 'price of', 'cost of']
    if any(keyword in message_lower for keyword in price_keywords):
        category = None
        product_name = None
        
        # Detect category
        if 'pizza' in message_lower:
            category = 'pizza'
        elif 'burger' in message_lower:
            category = 'burger'
        elif 'drink' in message_lower:
            category = 'drink'
        
        # Try to extract product name after price keywords
        for keyword in price_keywords:
            if keyword in message_lower:
                parts = message_lower.split(keyword)
                if len(parts) > 1:
                    potential_product = parts[1].strip()
                    # Clean up common words
                    potential_product = re.sub(r'\b(of|for|the|a|an)\b', '', potential_product).strip()
                    if potential_product:
                        product_name = potential_product.title()
                        break
        
        # Special case: if user just asks "pizza price" or "price of pizza"
        if category == 'pizza' and (not product_name or product_name.lower() == 'pizza'):
            product_name = 'pizza'
        
        return {
            "intent": "price_query", 
            "product_name": product_name, 
            "product_names": None,
            "category": category
        }
    
    # Check if message contains pizza-related terms without price keywords
    pizza_terms = ['pizza', 'pizzas']
    if any(term in message_lower for term in pizza_terms):
        # Check for info-seeking patterns first
        info_patterns = ['about', 'what is', 'tell me', 'describe', 'info', 'what\'s in']
        if any(pattern in message_lower for pattern in info_patterns):
            # Extract pizza name for info request
            specific_pizza_names = ['margherita', 'pepperoni', 'veggie', 'hawaiian', 'supreme', 'bbq', 'cheese']
            for name in specific_pizza_names:
                if name in message_lower:
                    return {
                        "intent": "product_info", 
                        "product_name": f"{name} pizza", 
                        "product_names": None,
                        "category": "pizza"
                    }
            # General pizza info request
            return {
                "intent": "product_info", 
                "product_name": "pizza", 
                "product_names": None,
                "category": "pizza"
            }
        
        # If it's a general pizza inquiry, treat as pizza types request
        specific_pizza_names = ['margherita', 'pepperoni', 'veggie', 'hawaiian', 'supreme', 'bbq']
        is_specific = any(name in message_lower for name in specific_pizza_names)
        
        if is_specific:
            # Extract the specific pizza name
            for name in specific_pizza_names:
                if name in message_lower:
                    return {
                        "intent": "price_query", 
                        "product_name": f"{name} pizza", 
                        "product_names": None,
                        "category": "pizza"
                    }
        else:
            return {
                "intent": "pizza_types", 
                "product_name": None, 
                "product_names": None,
                "category": "pizza"
            }
    
    return {
        "intent": "other", 
        "product_name": None, 
        "product_names": None,
        "category": None
    }
