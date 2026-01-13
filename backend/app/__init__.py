# PyPNM Web GUI - Flask Application
# SPDX-License-Identifier: Apache-2.0

from flask import Flask
from flask_cors import CORS


class CustomFlask(Flask):
    """Custom Flask class with modified Jinja2 delimiters for Vue.js compatibility."""
    jinja_options = Flask.jinja_options.copy()
    jinja_options.update(dict(
        variable_start_string='[[',
        variable_end_string=']]',
    ))


# Global socketio instance (may be None if not using agents)
socketio = None


def create_app():
    """Create and configure the Flask application."""
    global socketio
    
    app = CustomFlask(__name__, 
                static_folder='../../frontend/static',
                template_folder='../../frontend/templates')
    
    # Enable CORS for API calls
    CORS(app)
    
    # Load configuration
    app.config.from_object('app.core.config.Config')
    
    # Initialize agent WebSocket if enabled
    if app.config.get('ENABLE_AGENT_WEBSOCKET', False):
        try:
            from app.core.agent_manager import init_agent_websocket
            socketio = init_agent_websocket(
                app, 
                auth_token=app.config.get('AGENT_AUTH_TOKEN')
            )
            app.logger.info("Agent WebSocket support enabled")
        except ImportError as e:
            app.logger.warning(f"Agent WebSocket not available: {e}")
    
    # Register blueprints
    from app.routes import main_bp, api_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    
    return app
