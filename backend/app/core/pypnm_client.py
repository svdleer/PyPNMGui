# PyPNM Web GUI - PyPNM API Client
#
# Client wrapper for PyPNM FastAPI endpoints

import os
import json
import logging
import requests
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PyPNMConfig:
    """PyPNM server configuration."""
    # Use Docker gateway IP to reach host network services
    # Support both PYPNM_API_URL and PYPNM_BASE_URL environment variables
    base_url: str = None
    timeout: int = 180
    verify_ssl: bool = False
    
    def __post_init__(self):
        if self.base_url is None:
            self.base_url = os.environ.get('PYPNM_API_URL', os.environ.get('PYPNM_BASE_URL', 'http://172.17.0.1:8081'))


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
        
        # Spectrum analyzer needs longer timeout (full frequency sweep 300-1218 MHz)
        timeout = 300 if 'spectrumAnalyzer' in endpoint else self.config.timeout
        
        try:
            logger.debug(f"POST {url} with payload: {payload}")
            response = self.session.post(
                url,
                json=payload,
                timeout=timeout
            )
            
            # Log PyPNM errors
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                    logger.error(f"PyPNM returned {response.status_code}: {error_detail}")
                    if 'constellation' in endpoint.lower():
                        logger.error(f"=== CONSTELLATION ERROR DETAIL ===")
                        logger.error(f"Full error response: {json.dumps(error_detail, indent=2)}")
                except:
                    logger.error(f"PyPNM returned {response.status_code}: {response.text[:500]}")
                    if 'constellation' in endpoint.lower():
                        logger.error(f"=== CONSTELLATION ERROR (RAW) ===")
                        logger.error(f"Full response text: {response.text}")
            
            response.raise_for_status()
            
            # For archive responses, return binary content
            if expect_binary or payload.get('analysis', {}).get('output', {}).get('type') == 'archive':
                content_len = len(response.content)
                content_type = response.headers.get('content-type', '')
                logger.info(f"PyPNM returned {content_len} bytes, Content-Type: {content_type}")
                
                # Check if response is actually JSON (error response) vs binary archive
                # PyPNM may return JSON error even when archive was requested
                if 'application/json' in content_type or (content_len < 1000 and response.content.startswith(b'{')):
                    try:
                        json_response = response.json()
                        # Check if it's an error response (status != 0)
                        if isinstance(json_response, dict) and json_response.get('status', 0) != 0:
                            logger.error(f"PyPNM returned error: {json_response}")
                            return json_response
                        return json_response
                    except Exception as e:
                        logger.warning(f"Response looks like JSON but failed to parse: {e}")
                
                if content_len == 0:
                    logger.error("PyPNM returned empty content for archive request!")
                # Log first 200 bytes if not binary
                if content_len > 0 and content_len < 1000:
                    logger.warning(f"Small response ({content_len} bytes): {response.content[:200]}")
                return response.content
            
            result = response.json()
            logger.debug(f"PyPNM response from {endpoint}: status={result.get('status')}, keys={list(result.keys())[:10]}")
            if 'results' in result:
                result_val = result['results']
                if isinstance(result_val, dict):
                    logger.debug(f"Response 'results' is dict with keys: {list(result_val.keys())}")
                    if 'entries' in result_val:
                        logger.debug(f"Response 'results.entries' length: {len(result_val['entries'])}")
                elif isinstance(result_val, list):
                    logger.debug(f"Response 'results' is list with length: {len(result_val)}")
            return result
        
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
    
    def _get(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make GET request to PyPNM API."""
        url = f"{self.config.base_url}{endpoint}"
        try:
            logger.debug(f"GET {url} params={params}")
            response = self.session.get(url, params=params, timeout=self.config.timeout)
            if response.status_code >= 400:
                try:
                    logger.error(f"PyPNM returned {response.status_code}: {response.json()}")
                except Exception:
                    logger.error(f"PyPNM returned {response.status_code}: {response.text[:500]}")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to PyPNM at {self.config.base_url}")
            return {"status": "error", "message": f"PyPNM server not reachable at {self.config.base_url}."}
        except requests.exceptions.Timeout:
            logger.error("Timeout connecting to PyPNM")
            return {"status": "error", "message": "Request to PyPNM timed out"}
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from PyPNM: {e}")
            return {"status": "error", "message": f"PyPNM returned error: {e.response.status_code}",
                    "detail": e.response.text if e.response else None}
        except Exception as e:
            logger.exception("Unexpected error calling PyPNM")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    # ============== Agent Management ==============
    
    def get_agents(self) -> Dict[str, Any]:
        """
        Get list of connected agents.
        
        Endpoint: GET /api/agents
        """
        url = f"{self.config.base_url}/api/agents"
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get agents: {e}")
            return {"agents": [], "error": str(e)}
    
    def send_agent_task(self, agent_id: str, command: str, params: Dict[str, Any], 
                       timeout: float = 60.0) -> Dict[str, Any]:
        """
        Send a task to a specific agent via PyPNM API.
        
        This is for CMTS operations that need to go through an agent.
        
        Endpoint: POST /api/agents/{agent_id}/task
        
        Args:
            agent_id: The agent ID (e.g., 'pypnm-agent-lab')
            command: The command to execute (e.g., 'pnm_us_get_interfaces', 'cmts_get_modem_info')
            params: Command parameters
            timeout: Task timeout in seconds
            
        Returns:
            Task result from agent
        """
        url = f"{self.config.base_url}/api/agents/{agent_id}/task"
        try:
            logger.info(f"Sending agent task: {command} to {agent_id}")
            response = self.session.post(
                url,
                params={"command": command, "timeout": timeout},
                json=params,
                timeout=timeout + 10  # HTTP timeout slightly longer than task timeout
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Agent task result: success={result.get('success', False)}")
            return result
        except requests.exceptions.HTTPError as e:
            logger.error(f"Agent task HTTP error: {e}")
            return {"success": False, "error": f"HTTP error: {e.response.status_code}"}
        except Exception as e:
            logger.error(f"Agent task failed: {e}")
            return {"success": False, "error": str(e)}
    
    def get_first_agent_id(self) -> Optional[str]:
        """Get the ID of the first available agent."""
        agents = self.get_agents()
        agent_list = agents.get('agents', [])
        if agent_list:
            return agent_list[0].get('agent_id')
        return None
    
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
        Get RxMER (Receive Modulation Error Ratio) measurements.
        
        Endpoint: POST /docs/pnm/ds/ofdm/rxMer/getCapture
        
        Returns per-channel MER values in dB.
        Higher values indicate better signal quality (> 35 dB is good).
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
                    }
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"ui": {"theme": "light"}}
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
                "snmp": {"snmp_v2c": {"community": community}},
                "pnm_parameters": {
                    "tftp": {
                        "ipv4": tftp_ipv4,
                        "ipv6": tftp_ipv6 if tftp_ipv6 else "::1"
                    }
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"ui": {"theme": "light"}},
                "spectrum_analysis": {
                    "moving_average": {"points": 10}
                }
            },
            "capture_parameters": {}
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
        Get channel estimation coefficients.
        
        Endpoint: POST /docs/pnm/ds/ofdm/channelEstCoeff/getCapture
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
                    }
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"ui": {"theme": "light"}}
            }
        }
        
        return self._post("/docs/pnm/ds/ofdm/channelEstCoeff/getCapture", payload)
    
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
        Get modulation profile.

        Endpoint: POST /pnm/ds/modulation-profile
        """
        payload = {
            "mac_address": mac_address,
            "modem_ip": ip_address,
            "community": community,
            "tftp_server": tftp_ipv4,
        }
        return self._post("/pnm/ds/modulation-profile", payload)
    
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
        Get FEC summary statistics.
        
        Endpoint: POST /pnm/ds/fec
        
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
                "plot": {"ui": {"theme": "light"}}
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
        sample_duration: int = 30,
        output_type: str = "json"
    ) -> Dict[str, Any]:
        """
        Get power histogram.
        
        Endpoint: POST /docs/pnm/ds/histogram/getCapture
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
                    }
                }
            },
            "analysis": {
                "type": "basic",
                "output": {"type": output_type},
                "plot": {"ui": {"theme": "light"}}
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
        Get constellation display.
        
        Endpoint: POST /docs/pnm/ds/ofdm/constellationDisplay/getCapture
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
                "plot": {
                    "ui": {"theme": "light"},
                    "options": {"display_cross_hair": True}
                }
            },
            "capture_settings": {}
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
        
        Endpoint: POST /pnm/us/ofdma/preEqualizer/getCapture
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
                "plot": {"ui": {"theme": "light"}}
            }
        }
        return self._post("/pnm/us/ofdma/preEqualization/getCapture", payload)

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
    
    # ============== Upstream PNM (CMTS-side via PyPNM API) ==============
    
    def discover_rf_ports(
        self,
        cmts_ip: str,
        community: str = "public",
        write_community: Optional[str] = None,
        cm_mac_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Discover UTSC RF ports on a CMTS via PyPNM API.

        Endpoint: GET /pnm/us/utsc/ports

        Returns RF ports and their configurations.
        """
        params = {"cmts_ip": cmts_ip, "community": community,
                  "write_community": write_community or community}
        return self._get("/pnm/us/utsc/ports", params)

    def discover_modem_rf_port(
        self,
        cmts_ip: str,
        cm_mac_address: str,
        community: str = "public"
    ) -> Dict[str, Any]:
        """
        Discover the correct UTSC RF port for a specific modem.
        
        Endpoint: POST /pnm/us/spectrumAnalyzer/discoverRfPort
        
        Returns rf_port_ifindex, rf_port_description, cm_index, us_channels.
        """
        payload = {
            "cmts_ip": cmts_ip,
            "community": community,
            "cm_mac_address": cm_mac_address
        }
        return self._post("/pnm/us/spectrumAnalyzer/discoverRfPort", payload)

    def discover_modem_ofdma(
        self,
        cmts_ip: str,
        cm_mac_address: str,
        community: str = "public",
        write_community: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Discover modem's OFDMA channel on CMTS via PyPNM API.
        
        Endpoint: POST /pnm/us/ofdma/rxmer/discover
        
        Returns cm_index, ofdma_ifindex, ofdma_description.
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community or community
            },
            "cm_mac_address": cm_mac_address
        }
        return self._post("/pnm/us/ofdma/rxmer/discover", payload)
    
    def configure_bulk_destination(
        self,
        cmts_ip: str,
        dest_ip: str,
        community: str = "public",
        write_community: Optional[str] = None,
        dest_path: str = "./",
        index: int = 1,
        pnm_types: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Configure CMTS bulk data destination for PNM file uploads.

        Auto-detects vendor and configures the correct table(s):
        - All vendors: docsPnmBulkDataTransferCfgTable (standard)
        - Casa only:   additionally docsPnmCcapBulkDataControlTable + PnmTestSelector

        Must be called once before UTSC or US RxMER captures will upload to TFTP.
        /pnm/us/utsc/configure no longer calls this internally — caller is responsible.

        Endpoint: POST /pnm/us/bulk-destination

        Args:
            cmts_ip: CMTS IP address
            dest_ip: TFTP server IP
            community: SNMP read community
            write_community: SNMP write community
            dest_path: TFTP destination path (default: './')
            index: Table row index (default: 1)
            pnm_types: Casa PnmTestSelector bits:
                       'utsc'  - usTriggeredSpectrumCapture (bit8)
                       'rxmer' - usOfdmaRxMerPerSubcarrier (bit5)
                       'both'  - bit5 + bit8
                       Defaults to ['utsc', 'rxmer'] (both enabled).
        """
        if pnm_types is None:
            pnm_types = ['utsc', 'rxmer']
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community or community
            },
            "dest_ip": dest_ip,
            "dest_path": dest_path,
            "index": index,
            "pnm_types": pnm_types
        }
        return self._post("/pnm/us/bulk-destination", payload)

    def stop_utsc(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "public",
        write_community: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stop a running UTSC capture via PyPNM API.
        
        Endpoint: POST /pnm/us/utsc/stop
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community or community
            },
            "rf_port_ifindex": rf_port_ifindex
        }
        return self._post("/pnm/us/utsc/stop", payload)

    def clear_utsc(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "public",
        write_community: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clear/reset UTSC configuration on CMTS by destroying the row.
        
        Sets RowStatus=6 (destroy) to force reconfiguration with new parameters.
        
        Endpoint: POST /pnm/us/utsc/clear
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community or community
            },
            "rf_port_ifindex": rf_port_ifindex
        }
        return self._post("/pnm/us/utsc/clear", payload)

    def configure_utsc(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "private",
        write_community: Optional[str] = None,
        trigger_mode: int = 2,
        center_freq_hz: int = 30000000,
        span_hz: int = 60000000,
        num_bins: int = 800,
        output_format: Optional[int] = None,  # None = auto-detect
        window_function: int = 2,
        repeat_period_us: int = 100000,  # 100ms = Casa minimum (E6000 minimum is 50ms)
        freerun_duration_ms: int = 0,  # 0 = auto-calculate
        trigger_count: int = 10,
        filename: str = "utsc_capture",
        destination_index: int = 1,
        cm_mac_address: Optional[str] = None,
        logical_ch_ifindex: Optional[int] = None,
        cfg_index: int = 1
    ) -> Dict[str, Any]:
        """
        Configure UTSC test parameters via PyPNM API.
        
        Endpoint: POST /pnm/us/utsc/configure
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community or community
            },
            "rf_port_ifindex": rf_port_ifindex,
            "cfg_index": cfg_index,
            "trigger_mode": trigger_mode,
            "center_freq_hz": center_freq_hz,
            "span_hz": span_hz,
            "num_bins": num_bins,
            "window_function": window_function,
            "repeat_period_us": repeat_period_us,
            "freerun_duration_ms": freerun_duration_ms,
            "trigger_count": trigger_count,
            "filename": filename,
            "destination_index": destination_index,
        }
        # Only include output_format if explicitly provided (enables auto-detection)
        if output_format is not None:
            payload["output_format"] = output_format
        if cm_mac_address:
            payload["cm_mac_address"] = cm_mac_address
        if logical_ch_ifindex:
            payload["logical_ch_ifindex"] = logical_ch_ifindex
        logger.info(f"UTSC configure payload: {payload}")
        return self._post("/pnm/us/utsc/configure", payload)

    def start_utsc(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "private",
        write_community: Optional[str] = None,
        cfg_index: int = 1
    ) -> Dict[str, Any]:
        """
        Start UTSC test via PyPNM API.
        
        Endpoint: POST /pnm/us/utsc/start
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community or community
            },
            "rf_port_ifindex": rf_port_ifindex,
            "cfg_index": cfg_index
        }
        return self._post("/pnm/us/utsc/start", payload)

    def get_utsc_status(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "public",
        write_community: Optional[str] = None,
        cfg_index: int = 1
    ) -> Dict[str, Any]:
        """
        Get UTSC test status via PyPNM API.

        Endpoint: GET /pnm/us/utsc/status
        """
        params = {"cmts_ip": cmts_ip, "community": community,
                  "write_community": write_community or community,
                  "rf_port_ifindex": rf_port_ifindex, "cfg_index": cfg_index}
        return self._get("/pnm/us/utsc/status", params)

    def get_utsc_config(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "public",
        write_community: Optional[str] = None,
        cfg_index: int = 1
    ) -> Dict[str, Any]:
        """
        Get current UTSC configuration for an RF port.

        Endpoint: GET /pnm/us/utsc/config
        """
        params = {"cmts_ip": cmts_ip, "community": community,
                  "write_community": write_community or community,
                  "rf_port_ifindex": rf_port_ifindex, "cfg_index": cfg_index}
        return self._get("/pnm/us/utsc/config", params)

    def get_bulk_destinations(
        self,
        cmts_ip: str,
        community: str = "public",
        write_community: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List configured rows in docsPnmBulkDataTransferCfgTable.

        Endpoint: GET /pnm/us/bulk-destination
        """
        params = {"cmts_ip": cmts_ip, "community": community,
                  "write_community": write_community or community}
        return self._get("/pnm/us/bulk-destination", params)
    
    def get_upstream_spectrum_capture(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        tftp_ipv4: str,
        community: str = "public",
        tftp_ipv6: Optional[str] = None,
        output_type: str = "json",
        trigger_mode: int = 2,
        center_freq_hz: int = 30000000,
        span_hz: int = 80000000,
        num_bins: int = 800,
        filename: str = "utsc_capture",
        cm_mac: Optional[str] = None,
        logical_ch_ifindex: Optional[int] = None,
        repeat_period_ms: int = 400,       # 400ms: satisfies Casa 100ms floor + 120s/300files
        freerun_duration_ms: int = 120000,  # 120s: Casa minimum (is_freerun_trigger_valid)
        trigger_count: Optional[int] = None  # None = omit from payload, fixes E6000 freerun bug
    ) -> Dict[str, Any]:
        """
        Trigger CMTS-based Upstream Triggered Spectrum Capture (UTSC).
        
        Endpoint: POST /pnm/us/spectrumAnalyzer/getCapture
        
        UTSC is CMTS-based, not modem-based. Configures and initiates spectrum
        capture on CMTS using RF port ifIndex.
        
        Args:
            cmts_ip: CMTS IP address
            rf_port_ifindex: RF port ifIndex (e.g., 843071491 for cable-upstream)
            tftp_ipv4: TFTP server IP for file upload
            community: SNMP write community 
            trigger_mode: 2=FreeRunning, 6=CM MAC trigger
            center_freq_hz: Center frequency in Hz (default: 30 MHz)
            span_hz: Frequency span in Hz (default: 80 MHz)
            num_bins: Number of FFT bins (default: 800)
            filename: Output filename (CMTS adds timestamp)
            cm_mac: Cable modem MAC (required if trigger_mode=6)
            logical_ch_ifindex: Logical channel ifIndex (optional for trigger_mode=6)
            repeat_period_ms: Milliseconds between captures (default: 3000 = 3 seconds)
            freerun_duration_ms: Total duration for free-running mode (default: 300000 = 5 minutes)
            trigger_count: Number of captures to take (default: 20)
        
        Returns UTSC spectrum data for upstream channels (5-85 MHz typical).
        Files saved to TFTP with timestamp: {filename}_YYYY-MM-DD_HH.MM.SS.mmm
        """
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "rf_port_ifindex": rf_port_ifindex,
                "community": community
            },
            "tftp": {
                "ipv4": tftp_ipv4 if tftp_ipv4 else None,
                "ipv6": tftp_ipv6 if tftp_ipv6 else None
            },
            "trigger": {
                "cm_mac": cm_mac,
                "logical_ch_ifindex": logical_ch_ifindex
            } if cm_mac else {},
            "capture_parameters": {
                "trigger_mode": trigger_mode,
                "center_freq_hz": center_freq_hz,
                "span_hz": span_hz,
                "num_bins": num_bins,
                "filename": filename,
                "repeat_period_ms": repeat_period_ms,
                "freerun_duration_ms": freerun_duration_ms,
                **({} if trigger_count is None else {"trigger_count": trigger_count})  # Omit if None - E6000 bug workaround
            },
            "analysis": {
                "output_type": output_type
            }
        }
        logger.info(f"UTSC payload trigger_count={'OMITTED' if trigger_count is None else trigger_count}: {payload}")
        return self._post("/pnm/us/utsc/data", payload)
    
    def get_cmts_modems(
        self,
        cmts_ip: str,
        community: str = "public",
        limit: int = 10000,
        enrich: bool = False,
        modem_community: str = os.environ.get('MODEM_COMMUNITY', 'private')
    ) -> Dict[str, Any]:
        """
        Get cable modems from CMTS via PyPNM API (which uses agent for SNMP).
        
        Args:
            cmts_ip: CMTS IP address
            community: CMTS SNMP community
            limit: Maximum number of modems to return
            enrich: Whether to enrich modem data with additional info
            modem_community: SNMP community for individual modems
        
        Returns:
            Dictionary with 'success', 'modems', and optional 'error'
        """
        payload = {
            "cmts_ip": cmts_ip,
            "community": community,
            "limit": limit,
            "enrich": enrich,
            "modem_community": modem_community
        }
        
        try:
            # PyPNM API will route this through the agent
            response = self._post("/cmts/modems", payload)
            return response
        except Exception as e:
            logger.error(f"Error getting modems from CMTS {cmts_ip}: {e}")
            return {"success": False, "error": str(e)}
    
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
    
    # ============== CMTS Modem Discovery Endpoints ==============
# Global PyPNM client instance
_pypnm_client: Optional[PyPNMClient] = None


def get_pypnm_client() -> PyPNMClient:
    """Get or create global PyPNM client instance."""
    global _pypnm_client
    if _pypnm_client is None:
        _pypnm_client = PyPNMClient()
    return _pypnm_client
