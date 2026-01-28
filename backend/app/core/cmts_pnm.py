# CMTS PNM Operations via PyPNM API
# SPDX-License-Identifier: Apache-2.0
#
# Implements CMTS-side PNM operations (US OFDMA RxMER) by calling
# PyPNM FastAPI endpoints via HTTP.

"""
CMTS PNM Module for Upstream OFDMA RxMER

This module provides CMTS-side PNM operations by calling the PyPNM API.
The PyPNM API uses pysnmp for direct CMTS SNMP communication.

Key features:
- Discover modem's OFDMA channel ifIndex on CMTS
- Trigger US OFDMA RxMER measurement
- Poll measurement status

PyPNM API endpoints used:
- POST /docs/pnm/us/ofdma/rxmer/discover
- POST /docs/pnm/us/ofdma/rxmer/start
- POST /docs/pnm/us/ofdma/rxmer/status
"""

import os
import logging
import requests
from typing import Any, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def get_pypnm_api_url() -> str:
    """Get PyPNM API base URL from environment."""
    return os.environ.get('PYPNM_API_URL', os.environ.get('PYPNM_BASE_URL', 'http://172.17.0.1:8000'))


@dataclass
class UsOfdmaRxMerConfig:
    """Configuration for US OFDMA RxMER measurement"""
    cmts_ip: str
    ofdma_ifindex: int
    cm_mac_address: str
    community: str = "private"
    write_community: Optional[str] = None
    filename: str = "us_rxmer"
    pre_eq: bool = True
    num_averages: int = 1


class CmtsPnmClient:
    """
    Client for CMTS PNM operations via PyPNM API.
    
    Calls PyPNM API endpoints for CMTS SNMP operations.
    PyPNM API runs in a separate container with pysnmp installed.
    """
    
    def __init__(self, timeout: int = 60):
        """
        Initialize CMTS PNM client.
        
        Args:
            timeout: HTTP request timeout in seconds
        """
        self.base_url = get_pypnm_api_url()
        self.timeout = timeout
        self.session = requests.Session()
        logger.info(f"CmtsPnmClient initialized, PyPNM API: {self.base_url}")
    
    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make POST request to PyPNM API."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            logger.debug(f"POST {url}")
            response = self.session.post(url, json=payload, timeout=self.timeout)
            
            if response.status_code >= 400:
                logger.error(f"PyPNM API error {response.status_code}: {response.text[:500]}")
                return {"success": False, "error": f"API error: {response.status_code}"}
            
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.error(f"PyPNM API timeout: {url}")
            return {"success": False, "error": "Request timeout"}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"PyPNM API connection error: {e}")
            return {"success": False, "error": f"Connection error: {e}"}
        except Exception as e:
            logger.error(f"PyPNM API request failed: {e}")
            return {"success": False, "error": str(e)}
    
    def discover_modem_ofdma(
        self,
        cmts_ip: str,
        cm_mac: str,
        community: str = "private",
        write_community: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Discover modem's OFDMA channel on CMTS.
        
        Args:
            cmts_ip: CMTS IP address
            cm_mac: Cable modem MAC address
            community: SNMP community
            write_community: SNMP write community
            
        Returns:
            Dict with cm_index, ofdma_ifindex, success status
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community
            },
            "cm_mac_address": cm_mac
        }
        
        result = self._post("/docs/pnm/us/ofdma/rxmer/discover", payload)
        
        # Normalize response
        if "success" not in result:
            result["success"] = result.get("ofdma_ifindex") is not None
        
        return result
    
    def start_us_rxmer(self, config: UsOfdmaRxMerConfig) -> Dict[str, Any]:
        """
        Start Upstream OFDMA RxMER measurement.
        
        Args:
            config: US RxMER configuration
            
        Returns:
            Dict with success status and details
        """
        payload = {
            "cmts": {
                "cmts_ip": config.cmts_ip,
                "community": config.community,
                "write_community": config.write_community
            },
            "ofdma_ifindex": config.ofdma_ifindex,
            "cm_mac_address": config.cm_mac_address,
            "filename": config.filename,
            "pre_eq": config.pre_eq,
            "num_averages": config.num_averages
        }
        
        result = self._post("/docs/pnm/us/ofdma/rxmer/start", payload)
        
        # Normalize response
        if "success" not in result:
            result["success"] = "error" not in result
        
        return result
    
    def get_us_rxmer_status(
        self,
        cmts_ip: str,
        ofdma_ifindex: int,
        community: str = "private",
        write_community: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get US OFDMA RxMER measurement status.
        
        Args:
            cmts_ip: CMTS IP address
            ofdma_ifindex: OFDMA channel ifIndex
            community: SNMP community
            write_community: SNMP write community
            
        Returns:
            Dict with measurement status
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community
            },
            "ofdma_ifindex": ofdma_ifindex
        }
        
        result = self._post("/docs/pnm/us/ofdma/rxmer/status", payload)
        
        # Normalize response
        if "success" not in result:
            result["success"] = "error" not in result
        
        return result


# Convenience functions for Flask routes

def discover_modem_ofdma_sync(
    cmts_ip: str,
    cm_mac: str,
    community: str = "private"
) -> Dict[str, Any]:
    """
    Synchronous wrapper for OFDMA discovery.
    """
    client = CmtsPnmClient()
    return client.discover_modem_ofdma(cmts_ip, cm_mac, community)


def start_us_rxmer_sync(config: UsOfdmaRxMerConfig) -> Dict[str, Any]:
    """
    Synchronous wrapper for starting US RxMER measurement.
    """
    client = CmtsPnmClient()
    return client.start_us_rxmer(config)


def get_us_rxmer_status_sync(
    cmts_ip: str,
    ofdma_ifindex: int,
    community: str = "private"
) -> Dict[str, Any]:
    """
    Synchronous wrapper for getting US RxMER status.
    """
    client = CmtsPnmClient()
    return client.get_us_rxmer_status(cmts_ip, ofdma_ifindex, community)


# For backwards compatibility
PYPNM_AVAILABLE = True  # Always available via HTTP
