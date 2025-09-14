# chatbot/views.py
from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json
import logging
from django.shortcuts import render
from .nlp_utils import get_response

from paypal_project.paypal_api import PayPalClient

logger = logging.getLogger(__name__)
paypal_client = PayPalClient()

@method_decorator(csrf_exempt, name='dispatch')
class ChatbotAPI(View):
    def post(self, request):
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
        user_lower = user_message.lower()
        history = data.get("history", [])  # Optional: [["You", "text"], ["Bot", "text"], ...]
        logger.info(f"User message received: {user_message}")
        if not user_message:
            return JsonResponse({"error": "Empty message"}, status=400)
        reply = get_response(user_message, user_lower, history)
        logger.info(f"Bot reply: {reply}")
        history.append(["You", user_message])
        history.append(["Bot", reply])
        return JsonResponse({"reply": reply, "history": history})
    

class ChatbotUI(View):
    """Class-based view to render the chatbot frontend page."""
    template_name = "ChatbotUi/ChatbotUi.html"

    def get(self, request):
        return render(request, self.template_name)
