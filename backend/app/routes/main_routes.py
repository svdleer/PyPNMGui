# PyPNM Web GUI - Main Routes (Frontend Serving)
# SPDX-License-Identifier: Apache-2.0

from flask import send_from_directory, current_app
import os
from . import main_bp


def get_frontend_path():
    """Get the frontend templates path (works for both local and Docker)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    frontend_path = os.path.join(base_dir, '..', 'frontend', 'templates')
    if not os.path.exists(frontend_path):
        # Docker layout: /app/frontend/templates
        frontend_path = os.path.join(base_dir, 'frontend', 'templates')
    return frontend_path


@main_bp.route('/')
def index():
    """Serve the main application page."""
    return send_from_directory(get_frontend_path(), 'index.html')


@main_bp.route('/modem/<mac_address>')
def modem_details(mac_address):
    """Serve the modem details page."""
    return send_from_directory(get_frontend_path(), 'index.html')


@main_bp.route('/measurements')
def measurements():
    """Serve the measurements page."""
    return send_from_directory(get_frontend_path(), 'index.html')


@main_bp.route('/files')
def files():
    """Serve the files page."""
    return send_from_directory(get_frontend_path(), 'index.html')


@main_bp.route('/settings')
def settings():
    """Serve the settings page."""
    return send_from_directory(get_frontend_path(), 'index.html')


@main_bp.route('/ofdm-spectrum')
def ofdm_spectrum():
    """Serve the OFDM spectrum analysis page."""
    return send_from_directory(get_frontend_path(), 'ofdm_spectrum.html')

