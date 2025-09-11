from django.urls import path
from .views import ChatbotAPI,ChatbotUI

urlpatterns = [
    path("api/", ChatbotAPI.as_view(), name="chatbot_api"),
    path("", ChatbotUI.as_view(), name="chatbot_ui"),  # simple UI
]
