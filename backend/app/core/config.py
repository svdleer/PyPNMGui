# PyPNM Web GUI - Configuration

import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


class Config:
    """Application configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'

    # Authentication provider.
    # - internal: local username/password accounts from auth_db
    # - oidc: generic OpenID Connect login (Keycloak, Microsoft 365 / Entra ID, etc.)
    AUTH_PROVIDER = os.environ.get('AUTH_PROVIDER', 'internal').strip().lower()

    # Generic OIDC settings used when AUTH_PROVIDER=oidc.
    OIDC_PROVIDER_LABEL = os.environ.get('OIDC_PROVIDER_LABEL', 'Single Sign-On')
    OIDC_DISCOVERY_URL = os.environ.get('OIDC_DISCOVERY_URL', '')
    OIDC_CLIENT_ID = os.environ.get('OIDC_CLIENT_ID', '')
    OIDC_CLIENT_SECRET = os.environ.get('OIDC_CLIENT_SECRET', '')
    OIDC_SCOPES = os.environ.get('OIDC_SCOPES', 'openid profile email')
    OIDC_ADMIN_ROLES = os.environ.get('OIDC_ADMIN_ROLES', 'admin')
    OIDC_ADMIN_EMAILS = os.environ.get('OIDC_ADMIN_EMAILS', '')
    OIDC_VIEWER_ROLES = os.environ.get('OIDC_VIEWER_ROLES', 'viewer')
    OIDC_VIEWER_EMAILS = os.environ.get('OIDC_VIEWER_EMAILS', '')
    
    # PyPNM API Configuration (for direct API mode)
    PYPNM_API_URL = os.environ.get('PYPNM_API_URL', 'http://127.0.0.1:8000')
    PYPNM_API_TIMEOUT = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
    
    # Default SNMP Configuration
    DEFAULT_SNMP_COMMUNITY = os.environ.get('DEFAULT_SNMP_COMMUNITY', 'private')
    DEFAULT_SNMP_VERSION = 'v2c'
    DEFAULT_SNMP_TIMEOUT = 5
    DEFAULT_SNMP_RETRIES = 3
    CM_MODEM_LIMIT = _int_env('CM_MODEM_LIMIT', 10000)
    
    # TFTP Configuration — generic fallback
    TFTP_IPV4 = os.environ.get('TFTP_IPV4', '192.168.1.100')
    TFTP_IPV6 = os.environ.get('TFTP_IPV6', '')
    TFTP_PATH = os.environ.get('TFTP_PATH', '/tftpboot')

    # Vendor-specific TFTP server IPs.
    # If a vendor-specific var is not set, falls back to TFTP_IPV4.
    TFTP_COMMSCOPE  = os.environ.get('TFTP_COMMSCOPE', '') or os.environ.get('TFTP_ARRIS', '')   # CommScope / Arris E6000
    TFTP_CISCO      = os.environ.get('TFTP_CISCO',      '')   # Cisco cBR-8
    TFTP_CASA       = os.environ.get('TFTP_CASA',       '')   # Casa Systems 100G
    TFTP_ALT        = os.environ.get('TFTP_ALT',        '')   # CM-side / fallback alt

    # Vendor-specific TFTP upload root paths (sent as DestBaseUri / DestPath).
    # If not set, falls back to TFTP_DEST_PATH.
    TFTP_ROOT_COMMSCOPE = os.environ.get('TFTP_ROOT_COMMSCOPE', '')
    TFTP_ROOT_CISCO     = os.environ.get('TFTP_ROOT_CISCO',     '')
    TFTP_ROOT_CASA      = os.environ.get('TFTP_ROOT_CASA',      '')
    TFTP_ROOT_ALT       = os.environ.get('TFTP_ROOT_ALT',       '')
    
    # Data source mode: 'mock', 'agent', or 'direct'
    # - mock: Use mock data (for development/demo)
    # - agent: Use remote agent via WebSocket
    # - direct: Connect directly to PyPNM API
    DATA_MODE = os.environ.get('DATA_MODE', 'mock')
    
    # Use mock data instead of real API (legacy, use DATA_MODE instead)
    USE_MOCK_DATA = os.environ.get('USE_MOCK_DATA', 'True').lower() == 'true'
    
    # Agent WebSocket Configuration
    ENABLE_AGENT_WEBSOCKET = os.environ.get('ENABLE_AGENT_WEBSOCKET', 'False').lower() == 'true'
    AGENT_AUTH_TOKEN = os.environ.get('AGENT_AUTH_TOKEN', 'dev-token-change-in-production')
    AGENT_WEBSOCKET_PORT = int(os.environ.get('AGENT_WEBSOCKET_PORT', '5050'))

    # Maintenance mode — set MAINTENANCE_MODE=true to close the site to non-admins.
    # Admins (role=admin) can still log in and access everything normally.
    MAINTENANCE_MODE = os.environ.get('MAINTENANCE_MODE', 'false').lower() == 'true'
    MAINTENANCE_MESSAGE = os.environ.get(
        'MAINTENANCE_MESSAGE',
        'This service is temporarily unavailable. Please try again later.',
    )
