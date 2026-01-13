# PyPNM Remote Transport Layer
# SPDX-License-Identifier: Apache-2.0
#
# Provides SNMP/SSH operations via remote agent.
# Add to PyPNM: src/pypnm/transport/remote_transport.py

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

from .agent_manager import AgentManager, RemoteAgent, get_agent_manager

logger = logging.getLogger(__name__)


class RemoteAgentTransport:
    """
    Execute SNMP and SSH commands via remote agent.
    
    This class provides the same interface as direct SNMP/SSH operations
    but routes commands through a connected remote agent.
    
    Usage:
        transport = RemoteAgentTransport()
        
        # SNMP operations
        result = await transport.snmp_get("10.1.2.3", "1.3.6.1.2.1.1.1.0")
        result = await transport.snmp_walk("10.1.2.3", "1.3.6.1.2.1.1")
        
        # SSH operations (to CMTS)
        result = await transport.ssh_command("cmts.local", "show cable modem")
        
        # File retrieval
        content = await transport.get_pnm_file("/pnm/rxmer_aa-bb-cc.bin")
    """
    
    def __init__(
        self,
        agent_manager: Optional[AgentManager] = None,
        default_community: str = "private",
        default_timeout: float = 30
    ):
        self.agent_manager = agent_manager or get_agent_manager()
        self.default_community = default_community
        self.default_timeout = default_timeout
    
    def _get_agent(self, agent_id: Optional[str] = None) -> RemoteAgent:
        """Get an available agent."""
        agent = self.agent_manager.get_agent(agent_id)
        if not agent:
            raise RuntimeError(
                "No remote agent available. "
                "Ensure an agent is connected to the PyPNM server."
            )
        return agent
    
    # ==================== SNMP Operations ====================
    
    async def snmp_get(
        self,
        target_ip: str,
        oid: str,
        community: Optional[str] = None,
        version: str = "2c",
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute SNMP GET via remote agent.
        
        Args:
            target_ip: Target device IP address
            oid: OID to retrieve
            community: SNMP community string
            version: SNMP version (2c or 3)
            timeout: Command timeout in seconds
            agent_id: Specific agent to use (optional)
        
        Returns:
            Dict with 'success', 'value', and optionally 'error'
        """
        agent = self._get_agent(agent_id)
        
        result = await agent.execute(
            command="snmp_get",
            params={
                "target_ip": target_ip,
                "oid": oid,
                "community": community or self.default_community,
                "version": version,
            },
            timeout=timeout or self.default_timeout
        )
        
        return result
    
    async def snmp_walk(
        self,
        target_ip: str,
        oid: str,
        community: Optional[str] = None,
        version: str = "2c",
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute SNMP WALK via remote agent.
        
        Returns:
            Dict with 'success', 'values' (list), and optionally 'error'
        """
        agent = self._get_agent(agent_id)
        
        result = await agent.execute(
            command="snmp_walk",
            params={
                "target_ip": target_ip,
                "oid": oid,
                "community": community or self.default_community,
                "version": version,
            },
            timeout=timeout or self.default_timeout
        )
        
        return result
    
    async def snmp_set(
        self,
        target_ip: str,
        oid: str,
        value: Any,
        value_type: str = "s",
        community: Optional[str] = None,
        version: str = "2c",
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute SNMP SET via remote agent.
        
        Args:
            value_type: SNMP type (i=INTEGER, s=STRING, x=HEX, etc.)
        """
        agent = self._get_agent(agent_id)
        
        result = await agent.execute(
            command="snmp_set",
            params={
                "target_ip": target_ip,
                "oid": oid,
                "value": value,
                "type": value_type,
                "community": community or self.default_community,
                "version": version,
            },
            timeout=timeout or self.default_timeout
        )
        
        return result
    
    async def snmp_bulk_get(
        self,
        target_ip: str,
        oids: List[str],
        community: Optional[str] = None,
        version: str = "2c",
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute multiple SNMP GETs in one request."""
        agent = self._get_agent(agent_id)
        
        result = await agent.execute(
            command="snmp_bulk_get",
            params={
                "target_ip": target_ip,
                "oids": oids,
                "community": community or self.default_community,
                "version": version,
            },
            timeout=timeout or self.default_timeout
        )
        
        return result
    
    # ==================== CMTS/SSH Operations ====================
    
    async def cmts_command(
        self,
        cmts_host: str,
        command: str,
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute SSH command on CMTS via remote agent.
        
        Args:
            cmts_host: CMTS hostname or IP
            command: CLI command to execute
        
        Returns:
            Dict with 'success', 'output', and optionally 'error'
        """
        agent = self._get_agent(agent_id)
        
        result = await agent.execute(
            command="cmts_command",
            params={
                "cmts_host": cmts_host,
                "command": command,
            },
            timeout=timeout or self.default_timeout
        )
        
        return result
    
    # ==================== PNM File Operations ====================
    
    async def get_pnm_file(
        self,
        file_path: str,
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve PNM file from TFTP server via remote agent.
        
        Args:
            file_path: Path to file on TFTP server
        
        Returns:
            Dict with 'success', 'content_base64', 'size', and optionally 'error'
        """
        agent = self._get_agent(agent_id)
        
        result = await agent.execute(
            command="tftp_get",
            params={
                "path": file_path,
            },
            timeout=timeout or 60  # Longer timeout for file transfer
        )
        
        return result
    
    # ==================== Utility Operations ====================
    
    async def ping(
        self,
        target: str,
        count: int = 1,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ping a target from the agent's network."""
        agent = self._get_agent(agent_id)
        
        result = await agent.execute(
            command="ping",
            params={
                "target": target,
                "count": count,
            },
            timeout=10
        )
        
        return result
    
    async def trigger_pnm_measurement(
        self,
        target_ip: str,
        pnm_type: str,
        community: Optional[str] = None,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Trigger a PNM measurement on a cable modem.
        
        Args:
            pnm_type: Type of measurement (rxmer, spectrum, fec, etc.)
        """
        agent = self._get_agent(agent_id)
        
        result = await agent.execute(
            command="execute_pnm",
            params={
                "target_ip": target_ip,
                "pnm_type": pnm_type,
                "community": community or self.default_community,
            },
            timeout=60
        )
        
        return result


# Convenience function to create transport
def create_remote_transport(
    agent_manager: Optional[AgentManager] = None,
    **kwargs
) -> RemoteAgentTransport:
    """Create a RemoteAgentTransport instance."""
    return RemoteAgentTransport(agent_manager=agent_manager, **kwargs)
