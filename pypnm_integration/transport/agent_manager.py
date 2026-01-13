# PyPNM Remote Agent Manager
# SPDX-License-Identifier: Apache-2.0
#
# Manages WebSocket connections from remote agents.
# Add to PyPNM: src/pypnm/transport/agent_manager.py

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class RemoteAgent:
    """Represents a connected remote agent."""
    agent_id: str
    websocket: WebSocket
    capabilities: list = field(default_factory=list)
    connected_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    pending_requests: Dict[str, asyncio.Future] = field(default_factory=dict)
    
    @property
    def is_alive(self) -> bool:
        """Check if agent is still responsive."""
        return (time.time() - self.last_heartbeat) < 60
    
    async def execute(self, command: str, params: dict, timeout: float = 30) -> dict:
        """Execute a command on the remote agent."""
        request_id = str(uuid.uuid4())
        
        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future
        
        try:
            # Send command to agent
            await self.websocket.send_json({
                "type": "command",
                "request_id": request_id,
                "command": command,
                "params": params
            })
            
            # Wait for response
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
            
        except asyncio.TimeoutError:
            logger.error(f"Command timeout: {command} on agent {self.agent_id}")
            raise TimeoutError(f"Agent {self.agent_id} did not respond in time")
        finally:
            self.pending_requests.pop(request_id, None)
    
    def handle_response(self, request_id: str, result: dict):
        """Handle a response from the agent."""
        future = self.pending_requests.get(request_id)
        if future and not future.done():
            future.set_result(result)
    
    def handle_error(self, request_id: str, error: str):
        """Handle an error response from the agent."""
        future = self.pending_requests.get(request_id)
        if future and not future.done():
            future.set_exception(RuntimeError(error))


class AgentManager:
    """
    Manages connected remote agents.
    
    Usage with FastAPI:
    
        agent_manager = AgentManager(auth_token="your-secret")
        
        @app.websocket("/ws/agent")
        async def agent_endpoint(websocket: WebSocket):
            await agent_manager.handle_websocket(websocket)
    """
    
    def __init__(self, auth_token: Optional[str] = None):
        self.auth_token = auth_token
        self.agents: Dict[str, RemoteAgent] = {}
        self._websocket_to_agent: Dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()
        logger.info("AgentManager initialized")
    
    async def handle_websocket(self, websocket: WebSocket):
        """Handle incoming WebSocket connection from agent."""
        await websocket.accept()
        agent = None
        
        try:
            # Wait for authentication
            auth_msg = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=30
            )
            
            if auth_msg.get("type") != "auth":
                await websocket.close(code=4001, reason="Expected auth message")
                return
            
            # Validate token
            if self.auth_token and auth_msg.get("token") != self.auth_token:
                await websocket.close(code=4003, reason="Invalid token")
                logger.warning(f"Agent auth failed: invalid token")
                return
            
            agent_id = auth_msg.get("agent_id", f"agent-{uuid.uuid4().hex[:8]}")
            capabilities = auth_msg.get("capabilities", [])
            
            # Register agent
            agent = RemoteAgent(
                agent_id=agent_id,
                websocket=websocket,
                capabilities=capabilities
            )
            
            async with self._lock:
                # Disconnect existing agent with same ID
                if agent_id in self.agents:
                    old_agent = self.agents[agent_id]
                    try:
                        await old_agent.websocket.close(
                            code=4000, 
                            reason="Replaced by new connection"
                        )
                    except:
                        pass
                
                self.agents[agent_id] = agent
                self._websocket_to_agent[websocket] = agent_id
            
            logger.info(f"Agent connected: {agent_id} with capabilities: {capabilities}")
            
            # Send auth success
            await websocket.send_json({
                "type": "auth_success",
                "agent_id": agent_id
            })
            
            # Message loop
            while True:
                message = await websocket.receive_json()
                await self._handle_message(agent, message)
                
        except asyncio.TimeoutError:
            logger.warning("Agent auth timeout")
            await websocket.close(code=4002, reason="Auth timeout")
        except Exception as e:
            logger.error(f"Agent connection error: {e}")
        finally:
            # Cleanup
            if agent:
                async with self._lock:
                    self.agents.pop(agent.agent_id, None)
                    self._websocket_to_agent.pop(websocket, None)
                logger.info(f"Agent disconnected: {agent.agent_id}")
    
    async def _handle_message(self, agent: RemoteAgent, message: dict):
        """Handle message from agent."""
        msg_type = message.get("type")
        
        if msg_type == "heartbeat":
            agent.last_heartbeat = time.time()
            await agent.websocket.send_json({"type": "heartbeat_ack"})
            
        elif msg_type == "response":
            request_id = message.get("request_id")
            result = message.get("result", {})
            agent.handle_response(request_id, result)
            
        elif msg_type == "error":
            request_id = message.get("request_id")
            error = message.get("error", "Unknown error")
            agent.handle_error(request_id, error)
            
        else:
            logger.warning(f"Unknown message type from agent: {msg_type}")
    
    def get_agent(self, agent_id: Optional[str] = None) -> Optional[RemoteAgent]:
        """Get an agent by ID, or any available agent if ID not specified."""
        if agent_id:
            return self.agents.get(agent_id)
        
        # Return first available agent
        for agent in self.agents.values():
            if agent.is_alive:
                return agent
        return None
    
    def get_all_agents(self) -> list:
        """Get list of all connected agents."""
        return [
            {
                "agent_id": a.agent_id,
                "capabilities": a.capabilities,
                "connected_at": a.connected_at,
                "is_alive": a.is_alive
            }
            for a in self.agents.values()
        ]
    
    @property
    def has_agents(self) -> bool:
        """Check if any agents are connected."""
        return any(a.is_alive for a in self.agents.values())


# Singleton instance for easy import
_agent_manager: Optional[AgentManager] = None


def get_agent_manager() -> AgentManager:
    """Get the global AgentManager instance."""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager()
    return _agent_manager


def configure_agent_manager(auth_token: str) -> AgentManager:
    """Configure and return the global AgentManager instance."""
    global _agent_manager
    _agent_manager = AgentManager(auth_token=auth_token)
    return _agent_manager
