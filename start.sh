#!/usr/bin/env bash
set -euo pipefail

MODE="${RUN_TARGET:-backend}"
PORT_VAL="${PORT:-8080}"
echo "Starting service in mode: ${MODE} on port ${PORT_VAL}"

if [ "$MODE" = "frontend" ]; then
  exec /opt/venv/bin/streamlit run streamlit_chatbot.py --server.address 0.0.0.0 --server.port "${PORT_VAL}"
else
  # Respect GUNICORN_CMD_ARGS if provided, else default to 180s timeout
  EXTRA_ARGS=${GUNICORN_CMD_ARGS:-"--timeout 180"}
  echo "Starting gunicorn with EXTRA_ARGS: ${EXTRA_ARGS}"
  exec /opt/venv/bin/gunicorn paypal_project.wsgi:application --bind 0.0.0.0:"${PORT_VAL}" ${EXTRA_ARGS}
fi
