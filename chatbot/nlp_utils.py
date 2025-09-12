# chatbot/nlp_utils.py
import json
import re
import logging
import os
from openai import OpenAI
import os
from dotenv import load_dotenv


logger = logging.getLogger(__name__)

load_dotenv()

open_api_key = os.getenv("OPENAI_API_KEY")

def _strip_quotes(val: str | None) -> str | None:
    if val is None:
        return None
    return val.strip().strip('"').strip("'")

def _normalize_model_name(name: str) -> str:
    # Replace common Unicode dashes with ASCII '-'
    if not name:
        return name
    dash_chars = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
    trans = str.maketrans({c: '-' for c in dash_chars})
    return name.translate(trans).strip()

# Allow selecting the model via env; default to a stronger inexpensive model
openai_model = _normalize_model_name(_strip_quotes(os.getenv("OPENAI_MODEL", "gpt-4o-mini")) or "gpt-4o-mini")

# Optional: control temperature via env (default 0.0 for deterministic intent)
_temp_raw = _strip_quotes(os.getenv("OPENAI_TEMPERATURE", "0"))
try:
    openai_temperature = float(_temp_raw) if _temp_raw not in (None, "") else 0.0
except ValueError:
    openai_temperature = 0.0

if not open_api_key:
    raise ValueError("OPENAI_API_KEY not found. Please set it as an environment variable or in a .env file.")

client = OpenAI(api_key=_strip_quotes(open_api_key) if open_api_key else None)


def analyze_user_intent(message: str):
    """
    Analyze user message using OpenAI GPT to extract intent, product names, and category.
    Returns JSON like:
    {
      "intent": "price_query" or "list_products" or "pizza_types" or "product_info" or "suggest" or "other",
      "product_name": "<name or null>",
      "product_names": ["<name1>", "<name2>"] or null (for comparisons),
      "category": "<category like pizza, burger, etc. or null>",
      "search_terms": ["token1", "token2", ...]  // generic keywords to filter product names
    }
    """
    prompt = f"""
    You are a helpful assistant. Determine the user's intent, product names, and category.
    User message: "{message}"
    
    Respond ONLY in JSON format like:
    {{
        "intent": "price_query" or "list_products" or "pizza_types" or "product_info" or "suggest" or "other",
        "product_name": "<name or null>",
        "product_names": null,
        "category": "<category or null>",
        "search_terms": ["token1", "token2"]
    }}
    
    Intent guidelines:
    - "price_query": user asks for price of a specific product
    - "list_products": user wants to see all products/list/catalog
    - "pizza_types": user asks about different types of pizza, pizza varieties, or pizza menu
    - "product_info": user asks for information/description/details about a specific product
    - "suggest": user asks for recommendations or other options (e.g., "what else do you suggest", "recommend something")
    - "other": any other request
    
    Product name guidelines:
    - For all queries: set "product_name" and leave "product_names" as null
    - Extract the exact product names mentioned
    - Return null if no specific product is mentioned
    - For general queries like "pizza" or "pizzas", set product_name to "pizza"
    
    Category guidelines:
    - Identify the food category (e.g., pizza, burger, drink, dessert) when the user mentions one
    - Return null if no category is mentioned

    Search terms:
    - Always provide a short list (3-8) of generic, lowercase keywords that would appear in product names
    - Include singular/plural and common synonyms; e.g., for dessert include: dessert, brownie, cheesecake, pie, sundae, cake, ice cream
    - For burgers include: burger, cheeseburger, beef, patty
    - For burritos include: burrito, burito
    - For pizza include: pizza
    
    Examples:
    - "what pizzas do you have" → intent: "pizza_types", product_name: null, product_names: null, category: "pizza", search_terms:["pizza"]
    - "price of margherita pizza" → intent: "price_query", product_name: "margherita pizza", product_names: null, category: "pizza", search_terms:["margherita","pizza"]
    - "view dessert items" → intent: "list_products", product_name: null, product_names: null, category: "dessert", search_terms:["dessert","brownie","cheesecake","pie","sundae","cake","ice cream"]
    - "what else do you suggest" → intent: "suggest", product_name: null, product_names: null, category: null, search_terms:[]
    """

    try:
        response = client.chat.completions.create(
            model=openai_model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts intent, product names, and categories from user messages. Always respond in valid JSON format."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=openai_temperature
        )

        output_text = response.choices[0].message.content.strip()
        logger.debug(f"NLP raw output: {output_text}")
        print(f"NLP raw output: {output_text}")

        cleaned_text = re.sub(r"^```json\s*|```\s*$", "", output_text, flags=re.MULTILINE).strip()
        logger.debug(f"NLP cleaned output: {cleaned_text}")
        return json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        logger.error("JSON decode error in NLP: %s", e)
        print("JSON decode error in NLP:", e)
        return fallback_intent_analysis(message)
    except Exception as e:
        logger.error("Error calling model '%s': %s", openai_model, e)
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
    
    # Check for general list requests (broader synonyms)
    list_triggers = [
        'list', 'show all', 'all products', 'catalog', 'menu',
        'options', 'choices', 'what are the options', 'what options', 'what are my options',
        'do you have', 'what do you have', 'what can i get',
        'view all', 'view items', 'view all items', 'see all', 'see items', 'see menu',
        'browse menu', 'browse items', 'what is available', "what's available", 'available items',
        'all items', 'everything you have', 'everything', 'show me all'
    ]
    if any(word in message_lower for word in list_triggers):
        # Infer category from the message if possible
        cat = None
        if 'pizza' in message_lower:
            cat = 'pizza'
        elif 'burrito' in message_lower or 'burito' in message_lower:
            cat = 'burrito'
        elif 'burger' in message_lower or 'cheeseburger' in message_lower:
            cat = 'burger'
        elif 'sandwich' in message_lower or 'hoagie' in message_lower:
            cat = 'sandwich'
        elif 'salad' in message_lower or 'caesar' in message_lower:
            cat = 'salad'
        elif 'fries' in message_lower or 'onion rings' in message_lower or 'side' in message_lower:
            cat = 'side'
        elif any(k in message_lower for k in ['drink', 'soda', 'lemonade', 'milkshake', 'iced tea']):
            cat = 'drink'
        elif any(k in message_lower for k in ['dessert', 'brownie', 'cheesecake', 'pie']):
            cat = 'dessert'
        return {
            "intent": "list_products", 
            "product_name": None, 
            "product_names": None,
            "category": cat
        }

    # Single-word or short-category fallback (e.g., "burrito", "dessert")
    # Helps when the model isn't available or returns "other" for terse inputs
    tokens = re.findall(r"[a-zA-Z]+", message_lower)
    if 1 <= len(tokens) <= 3:
        cat_map = {
            'pizza': ('pizza', ['pizza']),
            'burrito': ('burrito', ['burrito','burito']),
            'burito': ('burrito', ['burrito','burito']),
            'burger': ('burger', ['burger','cheeseburger']),
            'sandwich': ('sandwich', ['sandwich','hoagie']),
            'salad': ('salad', ['salad','caesar']),
            'fries': ('side', ['fries','onion rings','side']),
            'side': ('side', ['side','fries','onion rings']),
            'drink': ('drink', ['drink','soda','lemonade','milkshake','tea']),
            'dessert': ('dessert', ['dessert','brownie','cheesecake','pie','sundae','cake','ice cream']),
        }
        for t in tokens:
            if t in cat_map:
                cat, terms = cat_map[t]
                return {
                    "intent": "list_products",
                    "product_name": None,
                    "product_names": None,
                    "category": cat,
                    "search_terms": terms,
                }

    # Suggestions / recommendations
    suggest_triggers = [
        'suggest', 'recommend', 'what else', 'anything else', 'something else',
        'other options', 'other items', 'more options', 'what more', 'what others'
    ]
    if any(word in message_lower for word in suggest_triggers):
        # Keep it generic; the view will use conversation context/history
        return {
            "intent": "suggest",
            "product_name": None,
            "product_names": None,
            "category": None,
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
