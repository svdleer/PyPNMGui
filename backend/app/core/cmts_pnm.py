# CMTS PNM Operations via PyPNM API
#
# Implements CMTS-side PNM operations (US OFDMA RxMER) by calling
# PyPNM FastAPI endpoints via HTTP.

"""
CMTS PNM Module for Upstream OFDMA RxMER

This module provides CMTS-side PNM operations by calling the PyPNM API.
PyPNM routes device operations through capability-matched agents.

Key features:
- Discover modem's OFDMA channel ifIndex on CMTS
- Trigger US OFDMA RxMER measurement
- Poll measurement status

PyPNM API endpoints used:
- POST /pnm/us/ofdma/rxmer/discover
- POST /pnm/us/ofdma/rxmer/start
- POST /pnm/us/ofdma/rxmer/status
"""

import os
import logging
import requests
from typing import Any, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _community_fields(
    community: Optional[str] = None,
    write_community: Optional[str] = None,
) -> Dict[str, str]:
    """Build credential fields while preserving explicit non-empty values."""
    fields: Dict[str, str] = {}
    if community is not None and (
        not isinstance(community, str) or community.strip()
    ):
        fields["community"] = community
    if write_community is not None and (
        not isinstance(write_community, str) or write_community.strip()
    ):
        fields["write_community"] = write_community
    return fields


def get_pypnm_api_url() -> str:
    """Get PyPNM API base URL from environment."""
    return os.environ.get('PYPNM_API_URL', os.environ.get('PYPNM_BASE_URL', 'http://172.17.0.1:8000'))


@dataclass
class UsOfdmaRxMerConfig:
    """Configuration for US OFDMA RxMER measurement"""
    cmts_ip: str
    ofdma_ifindex: int
    cm_mac_address: str
    community: Optional[str] = None
    write_community: Optional[str] = None
    filename: str = "us_rxmer"
    pre_eq: bool = True
    num_averages: int = 1
    destination_index: int = 0
    tftp_server: Optional[str] = None
    dest_path: Optional[str] = None


class CmtsPnmClient:
    """
    Client for CMTS PNM operations via PyPNM API.
    
    Calls PyPNM API endpoints for CMTS operations.
    PyPNM routes device communication through capability-matched agents.
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

    def _get(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make GET request to PyPNM API."""
        url = f"{self.base_url}{endpoint}"

        try:
            logger.debug("GET %s param_keys=%s", url, sorted((params or {}).keys()))
            response = self.session.get(url, params=params, timeout=self.timeout)

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
        community: Optional[str] = None,
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
                **_community_fields(community),
                **_community_fields(write_community=write_community)
            },
            "cm_mac_address": cm_mac
        }
        
        result = self._post("/pnm/us/ofdma/rxmer/discover", payload)
        
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
                **_community_fields(config.community),
                **_community_fields(write_community=config.write_community)
            },
            "ofdma_ifindex": config.ofdma_ifindex,
            "cm_mac_address": config.cm_mac_address,
            "filename": config.filename,
            "pre_eq": config.pre_eq,
            "num_averages": config.num_averages,
            "destination_index": config.destination_index,
        }
        if config.tftp_server:
            payload["tftp_server"] = config.tftp_server
        if config.dest_path:
            payload["dest_path"] = config.dest_path
        
        result = self._post("/pnm/us/ofdma/rxmer/start", payload)
        
        # Normalize response
        if "success" not in result:
            result["success"] = "error" not in result
        
        return result
    
    def get_us_rxmer_status(
        self,
        cmts_ip: str,
        ofdma_ifindex: int,
        community: Optional[str] = None,
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
        # GET /pnm/us/ofdma/rxmer/status?cmts_ip=...&ofdma_ifindex=...
        params = {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            **_community_fields(community, write_community),
        }

        result = self._get("/pnm/us/ofdma/rxmer/status", params=params)
        
        # Normalize response
        if "success" not in result:
            result["success"] = "error" not in result
        
        return result
    
    def get_bulk_destinations(
        self,
        cmts_ip: str,
        community: Optional[str] = None,
        write_community: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get list of configured bulk data transfer destinations.
        
        Args:
            cmts_ip: CMTS IP address
            community: SNMP community
            write_community: SNMP write community
            
        Returns:
            Dict with list of destinations
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                **_community_fields(community),
                **_community_fields(write_community=write_community)
            }
        }
        
        return self._post("/pnm/us/ofdma/rxmer/destinations", payload)
    
    def create_bulk_destination(
        self,
        cmts_ip: str,
        tftp_ip: str,
        community: Optional[str] = None,
        write_community: Optional[str] = None,
        port: int = 69,
        local_store: bool = True,
        dest_index: Optional[int] = None,
        dest_path: str = "./"
    ) -> Dict[str, Any]:
        """
        Create or configure a bulk data transfer destination for TFTP uploads.
        
        Args:
            cmts_ip: CMTS IP address
            tftp_ip: TFTP server IP address
            community: SNMP community
            write_community: SNMP write community
            port: TFTP port (default 69)
            local_store: Also store locally on CMTS
            dest_index: Destination index (1-10). If None, finds first available.
            dest_path: Upload path on TFTP server (default: './')
            
        Returns:
            Dict with destination_index and status
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                **_community_fields(community),
                **_community_fields(write_community=write_community)
            },
            "tftp_ip": tftp_ip,
            "port": port,
            "local_store": local_store,
            "dest_path": dest_path
        }
        
        if dest_index is not None:
            payload["dest_index"] = dest_index
        
        return self._post("/pnm/us/ofdma/rxmer/destinations/create", payload)


# Convenience functions for Flask routes

def discover_modem_ofdma_sync(
    cmts_ip: str,
    cm_mac: str,
    community: Optional[str] = None
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
    community: Optional[str] = None,
    write_community: Optional[str] = None
) -> Dict[str, Any]:
    """
    Synchronous wrapper for getting US RxMER status.
    """
    client = CmtsPnmClient()
    return client.get_us_rxmer_status(cmts_ip, ofdma_ifindex, community, write_community)


# For backwards compatibility
PYPNM_AVAILABLE = True  # Always available via HTTP
