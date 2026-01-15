"""
Custom PyPNM CableModem that uses agent transport
"""
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
    
    def is_ping_reachable(self) -> bool:
        """
        Override ping check - agent handles connectivity.
        Always return True since agent will handle connection errors.
        """
        return True
