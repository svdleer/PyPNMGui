# PyPNM Web GUI - Flask Application

from flask import Flask, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix


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
    
    # Handle proxy headers
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    
    # Get application root for transparent proxy (e.g., /cmtool)
    app_root = os.environ.get('APPLICATION_ROOT', '').rstrip('/')
    app.config['APP_ROOT'] = app_root
    
    print(f"[INFO] APPLICATION_ROOT env var: '{os.environ.get('APPLICATION_ROOT', 'NOT SET')}'")
    print(f"[INFO] APP_ROOT config: '{app_root}'")
    
    # Add middleware to handle base path prefix
    if app_root:
        def prefix_middleware(wsgi_app):
            def application(environ, start_response):
                script_name = environ.get('SCRIPT_NAME', '')
                path_info = environ.get('PATH_INFO', '')
                
                if path_info.startswith(app_root):
                    environ['SCRIPT_NAME'] = script_name + app_root
                    environ['PATH_INFO'] = path_info[len(app_root):]
                
                return wsgi_app(environ, start_response)
            return application
        
        app.wsgi_app = prefix_middleware(app.wsgi_app)
    
    # Add no-cache headers to prevent browser caching issues
    @app.after_request
    def add_no_cache_headers(response):
        if request.path.startswith('/static/') or response.content_type.startswith('text/html'):
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
    app.register_blueprint(pypnm_bp)  # pypnm_bp already has url_prefix='/api/pypnm'
    
    return app
