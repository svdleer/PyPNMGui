"""
PyPNM Custom SNMP Transport via PyPNM GUI Agent
Routes all SNMP operations through the agent's cm_proxy instead of direct SNMP
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor
import requests

logger = logging.getLogger(__name__)

# Thread pool for running sync requests in async context
_executor = ThreadPoolExecutor(max_workers=20)

# Request cache to avoid redundant SNMP requests
_cache = {}
_cache_ttl = 300  # Cache for 5 minutes (PNM data doesn't change rapidly)

# Pending request batching
_pending_gets = {}
_batch_delay = 0.05  # 50ms window to collect requests for batching

def clear_cache():
    """Clear the transport cache. Call when switching to a different modem."""
    global _cache
    _cache = {}
    logger.info("Transport cache cleared")

# Common SNMP MIB name to OID mappings
OID_MAP = {
    'sysDescr': '1.3.6.1.2.1.1.1',
    'sysObjectID': '1.3.6.1.2.1.1.2',
    'sysUpTime': '1.3.6.1.2.1.1.3',
    'sysContact': '1.3.6.1.2.1.1.4',
    'sysName': '1.3.6.1.2.1.1.5',
    'sysLocation': '1.3.6.1.2.1.1.6',
    'ifIndex': '1.3.6.1.2.1.2.2.1.1',
    'ifDescr': '1.3.6.1.2.1.2.2.1.2',
    'ifType': '1.3.6.1.2.1.2.2.1.3',
    'ifMtu': '1.3.6.1.2.1.2.2.1.4',
    'ifSpeed': '1.3.6.1.2.1.2.2.1.5',
    'ifPhysAddress': '1.3.6.1.2.1.2.2.1.6',
    'ifAdminStatus': '1.3.6.1.2.1.2.2.1.7',
    'ifOperStatus': '1.3.6.1.2.1.2.2.1.8',
    # DOCSIS MIBs
    'docsIfDownChannelId': '1.3.6.1.2.1.10.127.1.1.1.1.1',
    'docsIfDownChannelFrequency': '1.3.6.1.2.1.10.127.1.1.1.1.2',
    'docsIfDownChannelWidth': '1.3.6.1.2.1.10.127.1.1.1.1.3',
    'docsIfDownChannelModulation': '1.3.6.1.2.1.10.127.1.1.1.1.4',
    'docsIfDownChannelInterleave': '1.3.6.1.2.1.10.127.1.1.1.1.5',
    'docsIfDownChannelPower': '1.3.6.1.2.1.10.127.1.1.1.1.6',
    'docsIfDownChannelAnnex': '1.3.6.1.2.1.10.127.1.1.1.1.7',
    'docsIfUpChannelId': '1.3.6.1.2.1.10.127.1.1.2.1.1',
    'docsIfUpChannelFrequency': '1.3.6.1.2.1.10.127.1.1.2.1.2',
    'docsIfUpChannelWidth': '1.3.6.1.2.1.10.127.1.1.2.1.3',
    'docsIfUpChannelModulationProfile': '1.3.6.1.2.1.10.127.1.1.2.1.4',
    'docsIfUpChannelSlotSize': '1.3.6.1.2.1.10.127.1.1.2.1.5',
    'docsIfUpChannelTxTimingOffset': '1.3.6.1.2.1.10.127.1.1.2.1.6',
    'docsIfUpChannelRangingBackoffStart': '1.3.6.1.2.1.10.127.1.1.2.1.7',
    'docsIfUpChannelRangingBackoffEnd': '1.3.6.1.2.1.10.127.1.1.2.1.8',
    'docsIfUpChannelTxBackoffStart': '1.3.6.1.2.1.10.127.1.1.2.1.9',
    'docsIfUpChannelTxBackoffEnd': '1.3.6.1.2.1.10.127.1.1.2.1.10',
    'docsIfSigQSignalNoise': '1.3.6.1.2.1.10.127.1.1.4.1.5',
    'docsIfSigQMicroreflections': '1.3.6.1.2.1.10.127.1.1.4.1.6',
    # DOCSIS 3.1 MIBs
    'docsIf31CmDsOfdmChanChannelId': '1.3.6.1.4.1.4491.2.1.28.1.2.1.1',
    'docsIf31CmDsOfdmChannelSubcarrierZeroFreq': '1.3.6.1.4.1.4491.2.1.28.1.2.1.2',
    'docsIf31CmDsOfdmChanFirstActiveSubcarrier': '1.3.6.1.4.1.4491.2.1.28.1.2.1.3',
    'docsIf31CmDsOfdmChanLastActiveSubcarrier': '1.3.6.1.4.1.4491.2.1.28.1.2.1.4',
    'docsIf31CmDsOfdmChanNumActiveSubcarriers': '1.3.6.1.4.1.4491.2.1.28.1.2.1.5',
    'docsIf31CmDsOfdmChanSubcarrierSpacing': '1.3.6.1.4.1.4491.2.1.28.1.2.1.6',
    'docsIf31CmDsOfdmChanCyclicPrefix': '1.3.6.1.4.1.4491.2.1.28.1.2.1.7',
    'docsIf31CmDsOfdmChanRollOffPeriod': '1.3.6.1.4.1.4491.2.1.28.1.2.1.8',
    'docsIf31CmDsOfdmChanPlcFreq': '1.3.6.1.4.1.4491.2.1.28.1.2.1.9',
    'docsIf31CmDsOfdmChanNumPilots': '1.3.6.1.4.1.4491.2.1.28.1.2.1.10',
    'docsIf31CmDsOfdmChanTimeInterleaverDepth': '1.3.6.1.4.1.4491.2.1.28.1.2.1.11',
    'docsIf31CmDsOfdmChanChannelPower': '1.3.6.1.4.1.4491.2.1.28.1.2.1.14',
    'docsIf31CmStatusOfdmaUsT3Timeouts': '1.3.6.1.4.1.4491.2.1.28.1.10.1.5',
    'docsIf31CmStatusOfdmaUsT4Timeouts': '1.3.6.1.4.1.4491.2.1.28.1.10.1.6',
}

def resolve_oid(oid: str) -> str:
    """Resolve MIB name to numeric OID."""
    if oid[0].isdigit():
        # Already numeric
        return oid
    
    # Try to resolve from our map
    parts = oid.split('.')
    base_name = parts[0]
    
    if base_name in OID_MAP:
        numeric_base = OID_MAP[base_name]
        if len(parts) > 1:
            return f"{numeric_base}.{'.'.join(parts[1:])}"
        return numeric_base
    
    # Unknown name, return as-is and let backend handle it
    return oid


class AgentSnmpTransport:
    """
    Custom PyPNM SNMP transport that routes through PyPNM GUI agent.
    
    Replaces PyPNM's direct SNMP with API calls to the agent backend,
    which routes through cm_proxy (SSH to hop-access1-sh) to reach modems.
    """
    
    @staticmethod
    def get_result_value(result):
        """
        Static method to parse SNMP result values.
        PyPNM calls this to extract values from SNMP responses.
        
        Args:
            result: SNMP result (string from our transport or pysnmp result)
            
        Returns:
            List of values or single value
        """
        if isinstance(result, str):
            # Our transport returns strings, return as single-item list
            return [result] if result else []
        elif isinstance(result, list):
            return result
        else:
            # Unknown format
            return [str(result)] if result else []
    
    @staticmethod
    def snmp_get_result_value(result):
        """Alias for get_result_value for compatibility."""
        return AgentSnmpTransport.get_result_value(result)
    
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
                headers={"Content-Type": "application/json"},
                timeout=self._timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise
    
    async def _api_request_async(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make async API request using thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._api_request, endpoint, data)
    
    async def warmup_cache(self):
        """Pre-populate cache by walking common DOCSIS OID trees in parallel."""
        # Common OID trees to walk for channel data
        oid_trees = [
            '1.3.6.1.2.1.2.2.1.3',      # ifType
            '1.3.6.1.2.1.10.127.1.1.1', # docsIfDownstreamChannelTable
            '1.3.6.1.2.1.10.127.1.1.2', # docsIfUpstreamChannelTable  
            '1.3.6.1.2.1.10.127.1.1.4', # docsIfSignalQualityTable
        ]
        
        logger.info(f"Warming up cache for {self._target}...")
        start_time = time.time()
        
        # Walk all trees in parallel
        tasks = [self.walk(oid) for oid in oid_trees]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        elapsed = time.time() - start_time
        logger.info(f"Cache warmed up in {elapsed:.2f}s, {len(_cache)} entries cached")
    
    async def get(self, oid: str, timeout: Optional[int] = None, retries: Optional[int] = None) -> Optional[Any]:
        """
        SNMP GET via agent with intelligent caching from walk results.
        
        Args:
            oid: OID to query
            timeout: Timeout in seconds (ignored, uses backend timeout)
            retries: Number of retries (ignored, uses backend settings)
            
        Returns:
            Value from SNMP GET, or None on error
        """
        try:
            # Resolve OID name to numeric if needed
            numeric_oid = resolve_oid(oid)
            
            # Check if this exact OID is in a walk cache
            for cached_key in list(_cache.keys()):
                if cached_key.startswith('walk:'):
                    walk_data, walk_time = _cache[cached_key]
                    if time.time() - walk_time < _cache_ttl:
                        # Check if our OID is in this walk result
                        for walk_oid_str, walk_value in walk_data:
                            # Extract numeric OID from walk result (format: "iso.3.6.1...")
                            if walk_oid_str.startswith('iso.'):
                                walk_oid_numeric = walk_oid_str.replace('iso.', '1.')
                            else:
                                walk_oid_numeric = walk_oid_str
                            
                            # Check for exact match or if the walk OID contains our target
                            if walk_oid_numeric == numeric_oid or walk_oid_numeric.endswith('.' + numeric_oid) or numeric_oid in walk_oid_numeric:
                                logger.debug(f"Serving {numeric_oid} from walk cache: {walk_oid_str}")
                                return walk_value
            
            # Check individual GET cache
            cache_key = f"get:{self._target}:{numeric_oid}"
            now = time.time()
            if cache_key in _cache:
                cached_data, cached_time = _cache[cache_key]
                if now - cached_time < _cache_ttl:
                    logger.debug(f"Cache hit for get {numeric_oid}")
                    return cached_data
            
            # Not in cache, make the request
            result = await self._api_request_async("api/snmp/get", {
                "modem_ip": str(self._target),
                "oid": numeric_oid,
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
                        # Cache the result
                        _cache[cache_key] = (value, now)
                        return value
                # Cache the raw output
                _cache[cache_key] = (output, now)
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
        SNMP WALK via agent with caching.
        
        Args:
            oid: Base OID to walk
            
        Returns:
            List of (oid, value) tuples
        """
        try:
            # Resolve OID name to numeric if needed
            numeric_oid = resolve_oid(oid)
            
            # Check cache first
            cache_key = f"walk:{self._target}:{numeric_oid}"
            now = time.time()
            if cache_key in _cache:
                cached_data, cached_time = _cache[cache_key]
                if now - cached_time < _cache_ttl:
                    logger.debug(f"Cache hit for walk {numeric_oid}")
                    return cached_data
            
            result = await self._api_request_async("api/snmp/walk", {
                "modem_ip": str(self._target),
                "oid": numeric_oid,
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
                
                # Cache the results
                _cache[cache_key] = (results, now)
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
            
            result = await self._api_request_async("api/snmp/set", {
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
