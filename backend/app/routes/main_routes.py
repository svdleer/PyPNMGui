# PyPNM Web GUI - Main Routes (Frontend Serving)

from flask import send_from_directory, current_app, render_template, make_response, session
import os
from . import main_bp
from app.core.i18n import DEFAULT_LOCALE, get_messages, normalize_locale


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
    base_path = current_app.config.get('APP_ROOT', '') or os.environ.get('APPLICATION_ROOT', '').rstrip('/')
    current_app.logger.info(f"Rendering index with base_path: '{base_path}'")
    response = make_response(render_template(
        'index.html',
        base_path=base_path,
        cm_modem_limit=current_app.config.get('CM_MODEM_LIMIT', 10000),
        auth_username=session.get('username', ''),
        auth_role=session.get('role', 'user'),
        current_locale=normalize_locale(session.get('locale') or DEFAULT_LOCALE),
        locale_messages=get_messages(session.get('locale') or DEFAULT_LOCALE),
    ))
    # Prevent browser caching of HTML template
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


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
    base_path = current_app.config.get('APP_ROOT', '') or os.environ.get('APPLICATION_ROOT', '').rstrip('/')
    return render_template('ofdm_spectrum.html', base_path=base_path)


@main_bp.route('/spectrum-analyzer')
def spectrum_analyzer():
    """Serve the HTML5 live spectrum analyzer page."""
    base_path = os.environ.get('APPLICATION_ROOT', '/').rstrip('/')
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    static_path = os.path.join(base_dir, '..', 'frontend', 'static')
    if not os.path.exists(static_path):
        static_path = os.path.join(base_dir, 'frontend', 'static')
    return send_from_directory(static_path, 'spectrum-analyzer.html')


