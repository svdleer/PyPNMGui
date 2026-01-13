# PyPNM Web GUI - Routes
# SPDX-License-Identifier: Apache-2.0

from flask import Blueprint

# Main blueprint for serving frontend
main_bp = Blueprint('main', __name__)

# API blueprint for data endpoints
api_bp = Blueprint('api', __name__)

from . import main_routes, api_routes
