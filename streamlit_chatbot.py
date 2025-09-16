# chatbot_ui.py
import os
from dotenv import load_dotenv
import streamlit as st
import requests

st.set_page_config(page_title="PayPal Chatbot", page_icon="🤖")

# Load local .env for convenience (does not override real env)
load_dotenv()
st.title("💰 Chatbot")

# Backend URL can be overridden for deployments (e.g., Docker/Nginx setups)
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").strip().strip('"').strip("'")
CHATBOT_API_PATH = os.getenv("CHATBOT_API_PATH", "/chatbot/api/").strip().strip('"').strip("'")
if not BACKEND_URL.endswith("/"):
    BACKEND_URL += "/"
if CHATBOT_API_PATH.startswith("/"):
    CHATBOT_API_PATH = CHATBOT_API_PATH[1:]
CHATBOT_API = BACKEND_URL + CHATBOT_API_PATH

if "history" not in st.session_state:
    st.session_state.history = []
# Ensure the input key exists so we can safely clear it.
if "input" not in st.session_state:
    st.session_state["input"] = ""
# Apply a deferred reset (set in the previous run) before rendering the widget.
if st.session_state.get("_reset_input", False):
    st.session_state["_reset_input"] = False
    st.session_state["input"] = ""

# User input
user_input = st.text_input("You:", key="input")

if st.button("Send") and user_input.strip():
    try:
        # Only backend appends messages. Frontend sends last few turns.
        history_payload = st.session_state.history[-6:]
        response = requests.post(
            CHATBOT_API,
            json={"message": user_input.strip(), "history": history_payload},
            timeout=180
        )
        data = response.json()
        # Replace local history with backend-provided history
        st.session_state.history = data.get("history", st.session_state.history)
        bot_reply = data.get("reply", "No response")
    except requests.exceptions.ConnectionError:
        bot_reply = "Error: Could not connect to backend. Make sure Django server is running."
    except Exception as e:
        bot_reply = f"Error: {e}"
    finally:
        # Defer clearing the input to the next run to avoid Streamlit API errors.
        st.session_state["_reset_input"] = True
        try:
            st.rerun()
        except Exception:
            pass

# Display chat - newest conversation at top, oldest at bottom
# Group messages in pairs (User + Bot) and display newest pairs first
history_pairs = []
for i in range(0, len(st.session_state.history), 2):
    if i + 1 < len(st.session_state.history):
        user_msg = st.session_state.history[i]
        bot_msg = st.session_state.history[i + 1]
        history_pairs.append((user_msg, bot_msg))

# Display pairs in reverse order (newest first)
for user_msg, bot_msg in reversed(history_pairs):
    # Display user message first
    st.markdown(f"**{user_msg[0]}:** {user_msg[1]}")
    # Then display bot response
    st.markdown(f"<span style='color:green'><strong>{bot_msg[0]}:</strong> {bot_msg[1]}</span>", unsafe_allow_html=True)
    st.markdown("---")  
