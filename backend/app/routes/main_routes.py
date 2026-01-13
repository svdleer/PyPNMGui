# PyPNM Web GUI - Main Routes (Frontend Serving)
# SPDX-License-Identifier: Apache-2.0

from flask import send_from_directory
import os
from . import main_bp


# Get the frontend templates path
FRONTEND_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend', 'templates'))


@main_bp.route('/')
def index():
    """Serve the main application page."""
    return send_from_directory(FRONTEND_PATH, 'index.html')


@main_bp.route('/modem/<mac_address>')
def modem_details(mac_address):
    """Serve the modem details page."""
    return send_from_directory(FRONTEND_PATH, 'index.html')


@main_bp.route('/measurements')
def measurements():
    """Serve the measurements page."""
    return send_from_directory(FRONTEND_PATH, 'index.html')


@main_bp.route('/files')
def files():
    """Serve the files page."""
    return send_from_directory(FRONTEND_PATH, 'index.html')


@main_bp.route('/settings')
def settings():
    """Serve the settings page."""
    return send_from_directory(FRONTEND_PATH, 'index.html')
