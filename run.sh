#!/usr/bin/env bash
# Quick Start Script for Zillow Agent Lead Scraper Pro
cd "$(dirname "$0")"

# Check if venv exists
if [ -d "../.venv" ]; then
    PYTHON_CMD="../.venv/bin/python"
elif [ -d "./venv" ]; then
    PYTHON_CMD="./venv/bin/python"
else
    PYTHON_CMD="python3"
fi

echo "=========================================================="
echo "🏡 Starting Zillow Agent Lead Scraper Pro Web Dashboard..."
echo "=========================================================="
echo "Dashboard URL: http://localhost:8000"
echo "Press Ctrl+C to stop."
echo "----------------------------------------------------------"

exec $PYTHON_CMD server.py
