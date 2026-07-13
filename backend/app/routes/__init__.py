# PyPNM Web GUI - Routes

from flask import Blueprint

# Main blueprint for serving frontend
main_bp = Blueprint('main', __name__)

# API blueprint for data endpoints
api_bp = Blueprint('api', __name__)

# Auth/admin blueprint
auth_bp = Blueprint('auth', __name__)

# Optional topology module blueprint
topology_bp = Blueprint('topology', __name__)

# API documentation (Swagger) blueprint
apidoc_bp = Blueprint('apidoc', __name__)

from . import main_routes, api_routes, auth_routes, data_routes, topology_routes, apidoc_routes
