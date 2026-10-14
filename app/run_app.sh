#!/bin/bash
# Start the interactive simulator in the browser (http://localhost:8501).
# First time only:  uv venv app/.venv --python 3.12 && uv pip install --python app/.venv/bin/python -r app/requirements.txt
# Runs from app/ so the theme in app/.streamlit/config.toml is used.
cd "$(dirname "$0")"
exec .venv/bin/streamlit run app.py "$@"
