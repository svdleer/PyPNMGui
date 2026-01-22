"""
UTSC RF Port Discovery Module

Fast discovery of the correct UTSC RF port for a modem using PyPNM API.
Uses the modem's upstream logical channel to find the correct RF port.
"""

import logging
import requests
import os

logger = logging.getLogger(__name__)

# PyPNM API timeout
API_TIMEOUT = 60


def get_pypnm_api_url():
    """Get PyPNM API URL from environment or default."""
    # Try PYPNM_API_URL first, then PYPNM_BASE_URL
    return os.environ.get('PYPNM_API_URL', os.environ.get('PYPNM_BASE_URL', 'http://pypnm-api:8000'))


def discover_rf_port_for_modem(cmts_ip, community, mac_address):
    """
    Discover the correct UTSC RF port for a modem via PyPNM API.
    
    Returns dict with:
        - success: bool
        - rf_port_ifindex: int (the correct RF port)
        - rf_port_description: str
        - cm_index: int
        - us_channels: list of upstream channel ifIndexes
        - error: str (if failed)
    """
    result = {
        "success": False,
        "rf_port_ifindex": None,
        "rf_port_description": None,
        "cm_index": None,
        "us_channels": [],
        "error": None
    }
    
    pypnm_api_url = get_pypnm_api_url()
    logger.info(f"Discovering RF port for modem {mac_address} on CMTS {cmts_ip} via PyPNM API ({pypnm_api_url})")
    
    try:
        # Call PyPNM API to discover RF port
        response = requests.post(
            f"{pypnm_api_url}/docs/pnm/us/spectrumAnalyzer/discoverRfPort",
            json={
                "cmts_ip": cmts_ip,
                "cm_mac_address": mac_address,
                "community": community
            },
            timeout=API_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                result["success"] = True
                result["rf_port_ifindex"] = data.get("rf_port_ifindex")
                result["rf_port_description"] = data.get("rf_port_description")
                result["cm_index"] = data.get("cm_index")
                result["us_channels"] = data.get("us_channels", [])
                logger.info(f"Discovered RF port: {result['rf_port_ifindex']} ({result['rf_port_description']})")
            else:
                result["error"] = data.get("error", "Discovery failed")
                logger.warning(f"Discovery failed: {result['error']}")
        else:
            result["error"] = f"API returned {response.status_code}"
            logger.error(f"PyPNM API error: {response.status_code} - {response.text}")
            
    except requests.exceptions.Timeout:
        result["error"] = "PyPNM API timeout"
        logger.error("PyPNM API timeout")
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"Cannot connect to PyPNM API: {e}"
        logger.error(f"PyPNM API connection error: {e}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Discovery error: {e}")
    
    return result
