# PyPNM Web GUI - API Documentation (Swagger/OpenAPI)
# Proxies the PyPNM API's own OpenAPI spec so Swagger UI shows real endpoints.

import os
import requests
from flask import Blueprint, jsonify, render_template, current_app

apidoc_bp = Blueprint('apidoc', __name__)


@apidoc_bp.route('/openapi.json')
def openapi_spec():
    """Proxy the OpenAPI spec from the PyPNM API."""
    pypnm_url = os.environ.get('PYPNM_API_URL', os.environ.get('PYPNM_BASE_URL', 'http://127.0.0.1:8000')).rstrip('/')
    try:
        resp = requests.get(f"{pypnm_url}/openapi.json", timeout=5, verify=False)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": f"Could not fetch OpenAPI spec from PyPNM API: {e}"}), 502


@apidoc_bp.route('/')
def swagger_ui():
    """Serve Swagger UI."""
    base_path = current_app.config.get('APP_ROOT', '').rstrip('/')
    return render_template('apidoc.html', base_path=base_path)
