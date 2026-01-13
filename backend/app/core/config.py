# PyPNM Web GUI - Configuration
# SPDX-License-Identifier: Apache-2.0

import os


class Config:
    """Application configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'
    
    # PyPNM API Configuration (for direct API mode)
    PYPNM_API_URL = os.environ.get('PYPNM_API_URL', 'http://127.0.0.1:8000')
    PYPNM_API_TIMEOUT = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
    
    # Default SNMP Configuration
    DEFAULT_SNMP_COMMUNITY = os.environ.get('DEFAULT_SNMP_COMMUNITY', 'private')
    DEFAULT_SNMP_VERSION = 'v2c'
    DEFAULT_SNMP_TIMEOUT = 5
    DEFAULT_SNMP_RETRIES = 3
    
    # TFTP Configuration
    TFTP_IPV4 = os.environ.get('TFTP_IPV4', '192.168.1.100')
    TFTP_IPV6 = os.environ.get('TFTP_IPV6', '')
    TFTP_PATH = os.environ.get('TFTP_PATH', '/tftpboot')
    
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
    AGENT_WEBSOCKET_PORT = int(os.environ.get('AGENT_WEBSOCKET_PORT', '5051'))
