# PyPNM Web GUI - Raw WebSocket Handler for Agents
# SPDX-License-Identifier: Apache-2.0
#
# Simple WebSocket endpoint that works with websocket-client

import json
import logging
import threading
import time
import uuid
from queue import Queue, Empty
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PendingTask:
    """Represents a task waiting for agent response."""
    task_id: str
    command: str
    params: dict
    callback: Optional[Callable] = None
    created_at: float = field(default_factory=time.time)
    timeout: float = 30.0
    result: Optional[dict] = None
    completed: bool = False
    error: Optional[str] = None


@dataclass 
class ConnectedAgent:
    """Represents a connected remote agent."""
    agent_id: str
    ws: Any  # WebSocket connection
    capabilities: list
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    authenticated: bool = False


class SimpleAgentManager:
    """Simple WebSocket-based agent manager."""
    
    def __init__(self, auth_token: str = 'dev-token-change-me'):
        self.agents: dict[str, ConnectedAgent] = {}
        self.pending_tasks: dict[str, PendingTask] = {}
        self.auth_token = auth_token
        self._task_queues: dict[str, Queue] = {}
        self.logger = logging.getLogger(f'{__name__}.AgentManager')
    
    def handle_message(self, ws, message: str, agent_id: str = None) -> Optional[str]:
        """Handle incoming message from agent. Returns response message or None."""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'auth':
                return self._handle_auth(ws, data)
            
            elif msg_type == 'response':
                self._handle_response(data)
                return None
            
            elif msg_type == 'pong':
                self._handle_pong(ws)
                return None
            
            elif msg_type == 'error':
                self._handle_error(data)
                return None
            
            else:
                self.logger.warning(f"Unknown message type: {msg_type}")
                return None
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON: {e}")
            return json.dumps({'type': 'error', 'error': 'Invalid JSON'})
    
    def _handle_auth(self, ws, data: dict) -> str:
        """Handle agent authentication."""
        agent_id = data.get('agent_id')
        token = data.get('token')
        capabilities = data.get('capabilities', [])
        
        if token != self.auth_token:
            self.logger.warning(f"Auth failed for {agent_id}: invalid token")
            return json.dumps({
                'type': 'auth_response',
                'success': False,
                'error': 'Invalid token'
            })
        
        # Register agent
        agent = ConnectedAgent(
            agent_id=agent_id,
            ws=ws,
            capabilities=capabilities,
            authenticated=True
        )
        self.agents[agent_id] = agent
        
        self.logger.info(f"Agent authenticated: {agent_id} with {capabilities}")
        return json.dumps({
            'type': 'auth_success',
            'agent_id': agent_id,
            'message': 'Authenticated successfully'
        })
    
    def _handle_response(self, data: dict):
        """Handle task response from agent."""
        request_id = data.get('request_id')
        
        if request_id not in self.pending_tasks:
            self.logger.warning(f"Response for unknown task: {request_id}")
            return
        
        task = self.pending_tasks[request_id]
        task.completed = True
        task.result = data.get('result')
        task.error = data.get('error')
        
        # Put in queue if waiting
        if request_id in self._task_queues:
            self._task_queues[request_id].put(data)
        
        self.logger.info(f"Task completed: {request_id}")
    
    def _handle_pong(self, ws):
        """Handle pong from agent."""
        for agent in self.agents.values():
            if agent.ws == ws:
                agent.last_seen = time.time()
                break
    
    def _handle_error(self, data: dict):
        """Handle error from agent."""
        request_id = data.get('request_id')
        error = data.get('error')
        
        if request_id in self.pending_tasks:
            task = self.pending_tasks[request_id]
            task.completed = True
            task.error = error
            
            if request_id in self._task_queues:
                self._task_queues[request_id].put(data)
    
    def remove_agent(self, ws):
        """Remove agent by WebSocket connection."""
        to_remove = None
        for agent_id, agent in self.agents.items():
            if agent.ws == ws:
                to_remove = agent_id
                break
        
        if to_remove:
            del self.agents[to_remove]
            self.logger.info(f"Agent disconnected: {to_remove}")
    
    def get_available_agents(self) -> list:
        """Get list of connected agents."""
        return [
            {
                'agent_id': agent.agent_id,
                'capabilities': agent.capabilities,
                'connected_at': agent.connected_at,
                'last_seen': agent.last_seen,
                'authenticated': agent.authenticated
            }
            for agent in self.agents.values()
            if agent.authenticated
        ]
    
    def get_agent_for_capability(self, capability: str) -> Optional[ConnectedAgent]:
        """Find agent with required capability."""
        for agent in self.agents.values():
            if agent.authenticated and capability in agent.capabilities:
                return agent
        return None
    
    def send_task(self, agent_id: str, command: str, params: dict, timeout: float = 30.0) -> str:
        """Send task to agent. Returns task_id."""
        if agent_id not in self.agents:
            raise ValueError(f"Agent not connected: {agent_id}")
        
        agent = self.agents[agent_id]
        if not agent.authenticated:
            raise ValueError(f"Agent not authenticated: {agent_id}")
        
        task_id = str(uuid.uuid4())
        
        task = PendingTask(
            task_id=task_id,
            command=command,
            params=params,
            timeout=timeout
        )
        self.pending_tasks[task_id] = task
        self._task_queues[task_id] = Queue()
        
        # Send command to agent
        msg = json.dumps({
            'type': 'command',
            'request_id': task_id,
            'command': command,
            'params': params
        })
        
        try:
            agent.ws.send(msg)
            self.logger.info(f"Sent task {task_id} ({command}) to {agent_id}")
        except Exception as e:
            self.logger.error(f"Failed to send task: {e}")
            del self.pending_tasks[task_id]
            del self._task_queues[task_id]
            raise
        
        return task_id
    
    def send_task_sync(self, agent_id: str, command: str, params: dict, timeout: float = 30.0) -> str:
        """Send task and return task_id for waiting."""
        return self.send_task(agent_id, command, params, timeout)
    
    def wait_for_task(self, task_id: str, timeout: float = 30.0) -> Optional[dict]:
        """Wait for task result."""
        if task_id not in self._task_queues:
            return None
        
        try:
            result = self._task_queues[task_id].get(timeout=timeout)
            return result
        except Empty:
            return None
        finally:
            if task_id in self._task_queues:
                del self._task_queues[task_id]
            if task_id in self.pending_tasks:
                del self.pending_tasks[task_id]


# Global instance
_simple_agent_manager: Optional[SimpleAgentManager] = None


def get_simple_agent_manager() -> Optional[SimpleAgentManager]:
    """Get the agent manager instance."""
    return _simple_agent_manager


def init_simple_agent_manager(auth_token: str = None) -> SimpleAgentManager:
    """Initialize the agent manager."""
    global _simple_agent_manager
    _simple_agent_manager = SimpleAgentManager(auth_token or 'dev-token-change-me')
    return _simple_agent_manager
