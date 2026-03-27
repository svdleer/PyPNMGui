# PyPNM Web GUI - Flask Application

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
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

from app.core.auth_db import auth_db
from app.core.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, get_messages, normalize_locale, translate

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

    # Initialize auth storage and bootstrap admin account.
    auth_db.init_db()
    auth_db.ensure_bootstrap_admin()
    try:
        app.logger.info(
            "Auth DB ready (backend=%s, users=%s, admins=%s)",
            auth_db.backend,
            len(auth_db.list_users()),
            auth_db.admin_count(),
        )
        app.logger.info("Poller engine runs in PyPNM API — GUI is proxy-only")
    except Exception as exc:
        app.logger.error("Auth DB startup check failed: %s", exc)
    
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
    from app.routes import main_bp, api_bp, auth_bp, topology_bp
    from app.routes.pypnm_routes import pypnm_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(pypnm_bp)  # pypnm_bp already has url_prefix='/api/pypnm'
    enable_topology = os.environ.get('ENABLE_TOPOLOGY', 'false').lower() in {'1', 'true', 'yes', 'on'}
    if enable_topology:
        app.register_blueprint(topology_bp)
        app.logger.info('Topology module enabled')
    else:
        app.logger.info('Topology module disabled')

    @app.context_processor
    def inject_feature_flags():
        locale = session.get('locale') or DEFAULT_LOCALE
        locale = normalize_locale(locale)
        return {
            'enable_topology': enable_topology,
            'current_locale': locale,
            'supported_locales': SUPPORTED_LOCALES,
            't': lambda key, default=None: translate(locale, key, default),
            'locale_messages': get_messages(locale),
        }

    @app.before_request
    def hydrate_user_locale():
        if not session.get('user_id'):
            session.pop('locale', None)
            return None
        user_locale = session.get('locale')
        if user_locale:
            session['locale'] = normalize_locale(user_locale)
            return None
        user = auth_db.get_user_by_id(session.get('user_id'))
        session['locale'] = normalize_locale((user or {}).get('language_preference'))
        return None

    @app.before_request
    def maintenance_gate():
        """Block non-admin users when maintenance flag file exists or MAINTENANCE_MODE env is set."""
        import os
        flag_file = os.path.join(app.instance_path, 'MAINTENANCE')
        # Also check /app/data/MAINTENANCE (docker volume path)
        data_flag = '/app/data/MAINTENANCE'
        # Flag file takes priority over env var — allows instant toggle without restart.
        # /app/data/MAINTENANCE_OFF disables maintenance even when env var is true.
        if os.path.exists('/app/data/MAINTENANCE_OFF') or os.path.exists(os.path.join(app.instance_path, 'MAINTENANCE_OFF')):
            return None
        active = (
            os.environ.get('MAINTENANCE_MODE', '').lower() == 'true'
            or os.path.exists(flag_file)
            or os.path.exists(data_flag)
        )
        if not active:
            return None
        raw_path = request.path or ''
        base_path = (app.config.get('APP_ROOT', '') or '').rstrip('/')
        path = raw_path
        if base_path and raw_path == base_path:
            path = '/'
        elif base_path and raw_path.startswith(base_path + '/'):
            path = raw_path[len(base_path):]
        bypass_prefixes = ('/static/', '/login', '/logout', '/api/', '/health', '/ws/')
        if any(path.startswith(p) for p in bypass_prefixes):
            return None
        if session.get('role') == 'admin':
            return None
        return render_template(
            'maintenance.html',
            base_path=base_path,
            message=app.config.get('MAINTENANCE_MESSAGE', ''),
        ), 503

    @app.before_request
    def require_authentication():
        if request.method == 'OPTIONS':
            return None
        raw_path = request.path or ""
        base_path = (app.config.get('APP_ROOT', '') or '').rstrip('/')
        path = raw_path
        if base_path and raw_path == base_path:
            path = '/'
        elif base_path and raw_path.startswith(base_path + '/'):
            path = raw_path[len(base_path):]
        # Keep health checks, static assets and login available without auth.
        public_prefixes = (
            '/static/',
            '/login',
            '/logout',
            '/api/health',
            '/health',
            '/ws/agent',
            '/ws/utsc/',
        )
        if any(path.startswith(p) for p in public_prefixes):
            return None

        if session.get('user_id'):
            return None

        if path.startswith('/api/'):
            return jsonify({'status': 'error', 'message': 'Authentication required'}), 401

        base = base_path
        login_path = url_for('auth.login', next=path)
        if base and not login_path.startswith(base + '/'):
            login_path = f"{base}{login_path}"
        return redirect(login_path)
    
    return app
