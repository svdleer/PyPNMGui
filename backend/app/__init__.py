# PyPNM Web GUI - Flask Application
# SPDX-License-Identifier: Apache-2.0

from flask import Flask, request
from flask_cors import CORS


class CustomFlask(Flask):
    """Custom Flask class with modified Jinja2 delimiters for Vue.js compatibility."""
    jinja_options = Flask.jinja_options.copy()
    jinja_options.update(dict(
        variable_start_string='[[',
        variable_end_string=']]',
    ))


# Global websocket instance
sock = None


import os

def create_app():
    """Create and configure the Flask application."""
    global sock
    
    # Paths work for both local dev and Docker
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dir = os.path.join(base_dir, '..', 'frontend')
    if not os.path.exists(frontend_dir):
        # Docker layout: /app/frontend
        frontend_dir = os.path.join(base_dir, 'frontend')
    
    app = CustomFlask(__name__, 
                static_folder=os.path.join(frontend_dir, 'static'),
                template_folder=os.path.join(frontend_dir, 'templates'))
    
    # Add no-cache headers for static files to prevent browser caching issues
    @app.after_request
    def add_no_cache_headers(response):
        if request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    # Enable CORS for API calls
    CORS(app)
    
    # Load configuration
    app.config.from_object('app.core.config.Config')
    
    # Initialize WebSocket support for agents
    if app.config.get('ENABLE_AGENT_WEBSOCKET', True):
        try:
            from app.routes.ws_routes import init_websocket
            sock = init_websocket(app)
            if sock:
                app.logger.info("Agent WebSocket support enabled at /ws/agent")
        except Exception as e:
            app.logger.warning(f"Agent WebSocket not available: {e}")
    
    # Register blueprints
    from app.routes import main_bp, api_bp
    from app.routes.pypnm_routes import pypnm_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(pypnm_bp)
    
    return app
