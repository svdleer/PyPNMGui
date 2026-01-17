# PyPNM Web GUI - PyPNM API Client
# SPDX-License-Identifier: Apache-2.0
#
# Client wrapper for PyPNM FastAPI endpoints

import os
import logging
import requests
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PyPNMConfig:
    """PyPNM server configuration."""
    # Use Docker gateway IP to reach host network services
    base_url: str = os.environ.get('PYPNM_BASE_URL', 'http://172.17.0.1:8000')
    timeout: int = 60
    verify_ssl: bool = False


class PyPNMClient:
    """
    Client for PyPNM FastAPI server.
    
    PyPNM is a complete FastAPI server for DOCSIS PNM operations.
    This client wraps PyPNM's existing REST API endpoints.
    
    PyPNM API Documentation: https://www.pypnm.io/api/
    PyPNM Repository: https://github.com/PyPNMApps/PyPNM
    """
    
    def __init__(self, config: Optional[PyPNMConfig] = None):
        self.config = config or PyPNMConfig()
        self.session = requests.Session()
        self.session.verify = self.config.verify_ssl
        logger.info(f"PyPNM client initialized: {self.config.base_url}")
    
    def _build_cable_modem_request(
        self,
        mac_address: str,
        ip_address: str,
        snmp_community: str = "private",
        tftp_ipv4: Optional[str] = None,
        tftp_ipv6: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build PyPNM cable modem request payload.
        
        All PyPNM endpoints expect this structure.
        """
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {
                    "snmpV2C": {
                        "community": snmp_community
                    }
                }
            }
        }
        
        # Add TFTP parameters if provided (for PNM captures)
        if tftp_ipv4 or tftp_ipv6:
            payload["cable_modem"]["pnm_parameters"] = {
                "tftp": {
                    "ipv4": tftp_ipv4 or "",
                    "ipv6": tftp_ipv6 or ""
                }
            }
        
        return payload
    
    def _post(self, endpoint: str, payload: Dict[str, Any], expect_binary: bool = False) -> Union[Dict[str, Any], bytes]:
        """Make POST request to PyPNM API."""
        url = f"{self.config.base_url}{endpoint}"
        
        try:
            logger.debug(f"POST {url}")
            response = self.session.post(
                url,
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            
            # For archive responses, return binary content
            if expect_binary or payload.get('analysis', {}).get('output', {}).get('type') == 'archive':
                return response.content
            
            return response.json()
        
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to PyPNM at {self.config.base_url}")
            return {
                "status": "error",
                "message": f"PyPNM server not reachable at {self.config.base_url}. "
                          "Please ensure PyPNM is installed and running."
            }
        
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to PyPNM")
            return {
                "status": "error",
                "message": "Request to PyPNM timed out"
            }
        
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from PyPNM: {e}")
            return {
                "status": "error",
                "message": f"PyPNM returned error: {e.response.status_code}",
                "detail": e.response.text if e.response else None
            }
        
        except Exception as e:
            logger.exception(f"Unexpected error calling PyPNM")
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}"
            }
    
    # ============== System Information Endpoints ==============
    
    def get_sys_descr(self, mac_address: str, ip_address: str, 
                     community: str = "private") -> Dict[str, Any]:
        """
        Get cable modem system description.
        
        Endpoint: POST /system/sysDescr
        Returns parsed sysDescr with hardware/software details.
        """
        payload = self._build_cable_modem_request(mac_address, ip_address, community)
        return self._post("/system/sysDescr", payload)
    
    def get_uptime(self, mac_address: str, ip_address: str, 
                  community: str = "private") -> Dict[str, Any]:
        """
        Get cable modem uptime.
        
        Endpoint: POST /system/upTime
        """
        payload = self._build_cable_modem_request(mac_address, ip_address, community)
        return self._post("/system/upTime", payload)
    
    # ============== Event Log Endpoints ==============
    
    def get_event_log(self, mac_address: str, ip_address: str, 
                     community: str = "private") -> Dict[str, Any]:
        """
        Get cable modem event log.
        
        Endpoint: POST /docs/dev/eventLog
        """
        payload = self._build_cable_modem_request(mac_address, ip_address, community)
        return self._post("/docs/dev/eventLog", payload)
    
    # ============== DOCSIS 3.0 Channel Stats ==============
    
    def get_ds_scqam_stats(self, mac_address: str, ip_address: str, 
                          community: str = "private") -> Dict[str, Any]:
        """
        Get downstream SC-QAM channel statistics.
        
        Endpoint: POST /docs/if30/ds/scqam/chan/stats
        """
        payload = self._build_cable_modem_request(mac_address, ip_address, community)
        return self._post("/docs/if30/ds/scqam/chan/stats", payload)
    
    def get_us_atdma_stats(self, mac_address: str, ip_address: str, 
                          community: str = "private") -> Dict[str, Any]:
        """
        Get upstream ATDMA channel statistics.
        
        Endpoint: POST /docs/if30/us/atdma/chan/stats
        """
        payload = self._build_cable_modem_request(mac_address, ip_address, community)
        return self._post("/docs/if30/us/atdma/chan/stats", payload)
    
    # ============== DOCSIS 3.1 Channel Stats ==============
    
    def get_ds_ofdm_stats(self, mac_address: str, ip_address: str, 
                         community: str = "private") -> Dict[str, Any]:
        """
        Get downstream OFDM channel statistics.
        
        Endpoint: POST /docs/if31/ds/ofdm/chan/stats
        """
        payload = self._build_cable_modem_request(mac_address, ip_address, community)
        return self._post("/docs/if31/ds/ofdm/chan/stats", payload)
    
    def get_us_ofdma_stats(self, mac_address: str, ip_address: str, 
                          community: str = "private") -> Dict[str, Any]:
        """
        Get upstream OFDMA channel statistics.
        
        Endpoint: POST /docs/if31/us/ofdma/channel/stats
        """
        payload = self._build_cable_modem_request(mac_address, ip_address, community)
        return self._post("/docs/if31/us/ofdma/channel/stats", payload)
    
    # ============== PNM Measurements ==============
    
    def get_rxmer_capture(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        tftp_ipv6: Optional[str] = None,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        Trigger RxMER measurement capture.
        
        Endpoint: POST /docs/pnm/ds/ofdm/rxMer/getCapture
        
        Args:
            output_type: "json" or "archive" (ZIP with plots)
        """
        # Build PyPNM PnmSingleCaptureRequest format
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {
                    "snmpV2C": {
                        "community": community
                    }
                },
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else "::1"  # PyPNM requires both IPv4 and IPv6
                    }
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type}
            }
        }
        
        return self._post("/docs/pnm/ds/ofdm/rxMer/getCapture", payload)
    
    def get_spectrum_capture(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        tftp_ipv6: Optional[str] = None,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        Trigger spectrum analyzer capture.
        
        Endpoint: POST /docs/pnm/ds/spectrumAnalyzer/getCapture
        """
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {
                    "snmpV2C": {
                        "community": community
                    }
                },
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4 if tftp_ipv4 else None,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else None
                    }
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"ui": {"theme": "light"}}
            }
        }
        
        return self._post("/docs/pnm/ds/spectrumAnalyzer/getCapture", payload)
    
    def get_channel_estimation(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        tftp_ipv6: Optional[str] = None,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        Channel Estimation Coefficients capture with plots.
        
        Endpoint: POST /docs/pnm/ds/ofdm/channelEstCoeff/getCapture
        Returns: JSON with analysis or ZIP archive with CSV+plots
        """
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {"snmpV2C": {"community": community}},
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else "::1"
                    },
                    "capture": {"channel_ids": []}
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"enable": output_type == "archive"}
            }
        }
        return self._post("/docs/pnm/ds/ofdm/chanEstCoeff/getCapture", payload)
    
    def get_modulation_profile(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        tftp_ipv6: Optional[str] = None,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        Modulation Profile capture with plots.
        
        Endpoint: POST /docs/pnm/ds/ofdm/modulationProfile/getCapture
        Returns: JSON with analysis or ZIP archive with CSV+plots
        """
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {"snmpV2C": {"community": community}},
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else "::1"
                    },
                    "capture": {"channel_ids": []}
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"enable": output_type == "archive"}
            }
        }
        return self._post("/docs/pnm/ds/ofdm/modulationProfile/getCapture", payload)
    
    def get_fec_summary(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        tftp_ipv6: Optional[str] = None,
        fec_summary_type: int = 2,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        FEC Summary capture with plots.
        
        Endpoint: POST /docs/pnm/ds/ofdm/fecSummary/getCapture
        Returns: JSON with analysis or ZIP archive with CSV+plots
        
        Args:
            fec_summary_type: 2 = 10-minute interval, 3 = 24-hour interval
        """
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {"snmpV2C": {"community": community}},
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else "::1"
                    },
                    "capture": {"channel_ids": []}
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"enable": output_type == "archive"}
            },
            "capture_settings": {
                "fec_summary_type": fec_summary_type
            }
        }
        return self._post("/docs/pnm/ds/ofdm/fecSummary/getCapture", payload)
    
    def get_histogram(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        tftp_ipv6: Optional[str] = None,
        sample_duration: int = 60,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        Downstream Histogram capture with plots.
        
        Endpoint: POST /docs/pnm/ds/histogram/getCapture
        Returns: JSON with analysis or ZIP archive with CSV+plots
        """
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {"snmpV2C": {"community": community}},
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else "::1"
                    },
                    "capture": {"channel_ids": []}
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"enable": output_type == "archive"}
            },
            "capture_settings": {
                "sample_duration": sample_duration
            }
        }
        return self._post("/docs/pnm/ds/histogram/getCapture", payload)
    
    def get_constellation_display(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        tftp_ipv6: Optional[str] = None,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        Constellation Display capture with plots.
        
        Endpoint: POST /docs/pnm/ds/ofdm/constellationDisplay/getCapture
        Returns: JSON with analysis or ZIP archive with CSV+plots
        """
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {"snmpV2C": {"community": community}},
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else "::1"
                    },
                    "capture": {"channel_ids": []}
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"enable": output_type == "archive"}
            },
            "capture_settings": {
                "modulation_order_offset": 0,
                "number_sample_symbol": 1000
            }
        }
        return self._post("/docs/pnm/ds/ofdm/constellationDisplay/getCapture", payload)
    
    def get_us_ofdma_pre_equalization(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        tftp_ipv6: Optional[str] = None,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        Upstream OFDMA Pre-Equalization capture with plots.
        
        Endpoint: POST /docs/pnm/us/ofdma/preEqualizer/getCapture
        Returns: JSON with analysis or ZIP archive with CSV+plots
        """
        payload = {
            "cable_modem": {
                "mac_address": mac_address,
                "ip_address": ip_address,
                "snmp": {"snmpV2C": {"community": community}},
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else "::1"
                    },
                    "capture": {"channel_ids": []}
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"enable": output_type == "archive"}
            }
        }
        return self._post("/docs/pnm/us/ofdma/preEqualizer/getCapture", payload)

    # ============== Multi-RxMER (Long-term monitoring) ==============
    
    def start_multi_rxmer(
        self,
        mac_address: str,
        ip_address: str,
        tftp_ipv4: str,
        community: str = "private",
        interval_minutes: int = 5,
        duration_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Start multi-RxMER capture (long-term monitoring).
        
        Endpoint: POST /advance/multi/rxmer/start
        
        Returns operation_id for status checking.
        """
        payload = self._build_cable_modem_request(
            mac_address, ip_address, community, tftp_ipv4
        )
        
        payload["interval_minutes"] = interval_minutes
        payload["duration_hours"] = duration_hours
        
        return self._post("/advance/multi/rxmer/start", payload)
    
    def get_multi_rxmer_status(self, operation_id: str) -> Dict[str, Any]:
        """
        Check status of multi-RxMER operation.
        
        Endpoint: GET /advance/multi/rxmer/status/{operation_id}
        """
        url = f"{self.config.base_url}/advance/multi/rxmer/status/{operation_id}"
        
        try:
            response = self.session.get(url, timeout=self.config.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting multi-RxMER status: {e}")
            return {"status": "error", "message": str(e)}
    
    # ============== Health Check ==============
    
    def health_check(self) -> bool:
        """Check if PyPNM server is reachable."""
        try:
            response = self.session.get(
                f"{self.config.base_url}/docs",
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"PyPNM health check failed: {e}")
            return False


# Global PyPNM client instance
_pypnm_client: Optional[PyPNMClient] = None


def get_pypnm_client() -> PyPNMClient:
    """Get or create global PyPNM client instance."""
    global _pypnm_client
    if _pypnm_client is None:
        _pypnm_client = PyPNMClient()
    return _pypnm_client
