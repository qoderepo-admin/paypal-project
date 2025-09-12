#!/usr/bin/env bash
set -euo pipefail

MODE="${RUN_TARGET:-backend}"
PORT_VAL="${PORT:-8000}"
echo "Starting service in mode: ${MODE} on port ${PORT_VAL}"

if [ "$MODE" = "frontend" ]; then
  exec /opt/venv/bin/streamlit run streamlit_chatbot.py --server.address 0.0.0.0 --server.port "${PORT_VAL}"
else
  exec /opt/venv/bin/gunicorn paypal_project.wsgi:application --bind 0.0.0.0:"${PORT_VAL}"
fi

