"""
Custom PyPNM CableModem that uses agent transport
"""
# CRITICAL: Import and patch Snmp_v2c BEFORE importing CableModem
from pypnm.snmp.snmp_v2c import Snmp_v2c

# Monkey-patch Snmp_v2c static methods to work with our transport
_original_get_result_value = Snmp_v2c.get_result_value if hasattr(Snmp_v2c, 'get_result_value') else None

def _agent_get_result_value(result):
    """Wrapper that handles both agent transport strings and native pysnmp results."""
    import sys
    print(f"DEBUG get_result_value input: type={type(result)}, value={repr(result)[:100]}", file=sys.stderr)
    
    if isinstance(result, str):
        # Agent transport returns string directly - return as-is for parse()
        print(f"DEBUG returning string", file=sys.stderr)
        return result
    elif isinstance(result, list) and len(result) == 1:
        # If it's a single-element list, return the element
        print(f"DEBUG returning list[0]", file=sys.stderr)
        return result[0]
    elif _original_get_result_value:
        ret = _original_get_result_value(result)
        print(f"DEBUG original returned", file=sys.stderr)
        return ret
    else:
        print(f"DEBUG returning as-is", file=sys.stderr)
        return result

# Patch the class BEFORE importing CableModem
Snmp_v2c.get_result_value = staticmethod(_agent_get_result_value)
if hasattr(Snmp_v2c, 'snmp_get_result_value'):
    Snmp_v2c.snmp_get_result_value = staticmethod(_agent_get_result_value)

# NOW import CableModem after patching
from pypnm.docsis.cable_modem import CableModem as BaseCableModem
from pypnm.lib.inet import Inet
from pypnm.lib.mac_address import MacAddress
from pypnm_integration.transport.pypnm_agent_transport import AgentSnmpTransport


class AgentCableModem(BaseCableModem):
    """
    PyPNM CableModem that routes SNMP through PyPNM GUI agent.
    
    Usage:
        cm = AgentCableModem(
            mac_address=MacAddress("aa:bb:cc:dd:ee:ff"),
            inet=Inet("10.214.157.17"),
            backend_url="http://localhost:5050",
            write_community="m0d3m1nf0"
        )
    """
    
    def __init__(
        self,
        mac_address: MacAddress,
        inet: Inet,
        backend_url: str = "http://localhost:5050",
        write_community: str = "private",
        **kwargs
    ):
        """
        Initialize CableModem with agent transport.
        
        Args:
            mac_address: Modem MAC address
            inet: Modem IP address
            backend_url: PyPNM GUI backend API URL
            write_community: SNMP write community (passed to agent)
        """
        # Initialize parent with agent transport
        super().__init__(
            mac_address=mac_address,
            inet=inet,
            write_community=write_community,
            **kwargs
        )
        
        # Replace SNMP transport with agent transport
        self._snmp = AgentSnmpTransport(
            backend_url=backend_url,
            target=str(inet),
            community=write_community  # Default to write for operations
        )
        
        # Store backend URL for reference
        self._backend_url = backend_url
        self._cache_warmed = False
    
    async def _ensure_cache_warm(self):
        """Ensure cache is warmed up before first query."""
        if not self._cache_warmed:
            await self._snmp.warmup_cache()
            self._cache_warmed = True
    
    async def getDocsIfDownstreamChannel(self, *args, **kwargs):
        """Override to warm cache before querying."""
        await self._ensure_cache_warm()
        return await super().getDocsIfDownstreamChannel(*args, **kwargs)
    
    async def getDocsIfUpstreamChannelEntry(self, *args, **kwargs):
        """Override to warm cache before querying."""
        await self._ensure_cache_warm()
        return await super().getDocsIfUpstreamChannelEntry(*args, **kwargs)
    
    async def getDocsIfSignalQuality(self, *args, **kwargs):
        """Override to warm cache before querying."""
        await self._ensure_cache_warm()
        return await super().getDocsIfSignalQuality(*args, **kwargs)
    
    def is_ping_reachable(self) -> bool:
        """
        Override ping check - agent handles connectivity.
        Always return True since agent will handle connection errors.
        """
        return True
