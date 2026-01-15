"""
PyPNM Custom SNMP Transport via PyPNM GUI Agent
Routes all SNMP operations through the agent's cm_proxy instead of direct SNMP
"""
import asyncio
import logging
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)


class AgentSnmpTransport:
    """
    Custom PyPNM SNMP transport that routes through PyPNM GUI agent.
    
    Replaces PyPNM's direct SNMP with API calls to the agent backend,
    which routes through cm_proxy (SSH to hop-access1-sh) to reach modems.
    """
    
    def __init__(self, backend_url: str = "http://localhost:5050", target: str = "", community: str = "public"):
        """
        Initialize agent transport.
        
        Args:
            backend_url: PyPNM GUI backend API URL
            target: Target IP address (modem)
            community: SNMP community string
        """
        # Store params but don't call parent init - we're replacing the transport entirely
        self._target = target
        self._community = community
        self._timeout = 30  # PyPNM expects this
        self._retries = 3   # PyPNM expects this
        self.backend_url = backend_url.rstrip('/')
        self._session = requests.Session()
        self._session.timeout = 30
        
    def _api_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make API request to backend."""
        try:
            response = self._session.post(
                f"{self.backend_url}/{endpoint}",
                json=data,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise
    
    async def get(self, oid: str, timeout: Optional[int] = None, retries: Optional[int] = None) -> Optional[Any]:
        """
        SNMP GET via agent.
        
        Args:
            oid: OID to query
            timeout: Timeout in seconds (ignored, uses backend timeout)
            retries: Number of retries (ignored, uses backend settings)
            
        Returns:
            Value from SNMP GET, or None on error
        """
        try:
            result = self._api_request("api/snmp/get", {
                "modem_ip": str(self._target),
                "oid": oid,
                "community": self._community
            })
            
            if result.get("success"):
                # Parse SNMP output: "OID = TYPE: value"
                output = result.get("output", "")
                if "=" in output:
                    value_part = output.split("=", 1)[1].strip()
                    if ":" in value_part:
                        value = value_part.split(":", 1)[1].strip()
                        # Remove quotes if present
                        value = value.strip('"')
                        return value
                return output
            else:
                logger.warning(f"SNMP GET failed: {result.get('error')}")
                return None
                
        except Exception as e:
            logger.error(f"SNMP GET error for {oid}: {e}")
            return None
    
    async def get_next(self, oid: str) -> Optional[tuple]:
        """
        SNMP GETNEXT via agent (walk single step).
        
        Args:
            oid: Starting OID
            
        Returns:
            Tuple of (next_oid, value) or None
        """
        # PyPNM doesn't use getnext directly, uses walk
        # For now, return None to indicate not supported
        logger.warning("GETNEXT not implemented in agent transport, use walk()")
        return None
    
    async def walk(self, oid: str) -> list:
        """
        SNMP WALK via agent.
        
        Args:
            oid: Base OID to walk
            
        Returns:
            List of (oid, value) tuples
        """
        try:
            result = self._api_request("api/snmp/walk", {
                "modem_ip": str(self._target),
                "oid": oid,
                "community": self._community
            })
            
            if result.get("success"):
                output = result.get("output", "")
                # Parse walk output: each line is "OID = TYPE: value"
                results = []
                for line in output.strip().split('\n'):
                    if '=' in line:
                        oid_part, value_part = line.split('=', 1)
                        oid_str = oid_part.strip()
                        if ':' in value_part:
                            value = value_part.split(':', 1)[1].strip().strip('"')
                        else:
                            value = value_part.strip()
                        results.append((oid_str, value))
                return results
            else:
                logger.warning(f"SNMP WALK failed: {result.get('error')}")
                return []
                
        except Exception as e:
            logger.error(f"SNMP WALK error for {oid}: {e}")
            return []
    
    async def set(self, oid: str, value: Any, value_type: Any) -> bool:
        """
        SNMP SET via agent.
        
        Args:
            oid: OID to set
            value: Value to set
            value_type: SNMP type (Integer32, OctetString, etc.)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Map PyPNM types to snmpset type codes
            type_map = {
                'Integer32': 'i',
                'OctetString': 's',
                'Gauge32': 'u',
                'IpAddress': 'a',
                'Counter32': 'c',
                'TimeTicks': 't',
            }
            
            type_name = getattr(value_type, '__name__', str(value_type))
            snmp_type = type_map.get(type_name, 's')
            
            # For OctetString binary data (like IP addresses), convert to hex
            if snmp_type == 's' and isinstance(value, bytes):
                # Convert bytes to hex string for SNMP
                value = value.hex()
                snmp_type = 'x'
            
            result = self._api_request("api/snmp/set", {
                "modem_ip": str(self._target),
                "oid": oid,
                "value": str(value),
                "type": snmp_type,
                "community": self._community
            })
            
            if result.get("success"):
                return True
            else:
                logger.warning(f"SNMP SET failed for {oid}: {result.get('error')}")
                return False
                
        except Exception as e:
            logger.error(f"SNMP SET error for {oid}={value}: {e}")
            return False
    
    def close(self):
        """Close transport session."""
        if hasattr(self, '_session'):
            self._session.close()
