#!/bin/bash
# PyPNM Web GUI - Start Script
# SPDX-License-Identifier: Apache-2.0

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Change to backend directory
cd "$SCRIPT_DIR/backend"

# Start Flask application
echo "Starting PyPNM Web GUI..."
echo "Access the application at: http://127.0.0.1:5050"
echo ""
python run.py
