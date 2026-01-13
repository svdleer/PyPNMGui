# PyPNM Web GUI - WebSocket Agent Manager
# SPDX-License-Identifier: Apache-2.0
#
# This module handles WebSocket connections from remote agents
# running on Jump Servers.

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from queue import Queue, Empty

try:
    from flask_socketio import SocketIO, emit, disconnect
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    SocketIO = None  # Define as None to avoid NameError
    print("WARNING: flask-socketio not installed. Agent support disabled.")


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
    sid: str  # Socket.IO session ID
    capabilities: list[str]
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    authenticated: bool = False


class AgentManager:
    """Manages connections to remote agents and task dispatching."""
    
    def __init__(self, auth_token: str = None):
        self.agents: dict[str, ConnectedAgent] = {}
        self.pending_tasks: dict[str, PendingTask] = {}
        self.auth_token = auth_token or 'dev-token'
        self.socketio: Optional[SocketIO] = None
        self.logger = logging.getLogger(f'{__name__}.AgentManager')
        
        # Task result queues for synchronous waiting
        self._task_queues: dict[str, Queue] = {}
    
    def init_app(self, app, socketio: SocketIO):
        """Initialize with Flask app and SocketIO instance."""
        self.socketio = socketio
        self._register_handlers()
        self.logger.info("Agent WebSocket handlers registered")
    
    def _register_handlers(self):
        """Register SocketIO event handlers."""
        if not self.socketio:
            return
        
        @self.socketio.on('connect', namespace='/agent')
        def handle_connect():
            self.logger.info(f"Agent connection attempt from {self._get_sid()}")
        
        @self.socketio.on('disconnect', namespace='/agent')
        def handle_disconnect():
            sid = self._get_sid()
            self._remove_agent_by_sid(sid)
            self.logger.info(f"Agent disconnected: {sid}")
        
        @self.socketio.on('auth', namespace='/agent')
        def handle_auth(data):
            sid = self._get_sid()
            agent_id = data.get('agent_id')
            token = data.get('token')
            capabilities = data.get('capabilities', [])
            
            if token != self.auth_token:
                self.logger.warning(f"Auth failed for agent {agent_id}: invalid token")
                emit('auth_response', {'success': False, 'error': 'Invalid token'})
                disconnect()
                return
            
            # Register agent
            agent = ConnectedAgent(
                agent_id=agent_id,
                sid=sid,
                capabilities=capabilities,
                authenticated=True
            )
            self.agents[agent_id] = agent
            
            self.logger.info(f"Agent authenticated: {agent_id} with capabilities: {capabilities}")
            emit('auth_response', {'success': True, 'message': 'Authenticated'})
        
        @self.socketio.on('task_response', namespace='/agent')
        def handle_task_response(data):
            task_id = data.get('task_id')
            
            if task_id not in self.pending_tasks:
                self.logger.warning(f"Response for unknown task: {task_id}")
                return
            
            task = self.pending_tasks[task_id]
            task.completed = True
            task.result = data.get('result')
            task.error = data.get('error')
            
            # Put result in queue if waiting
            if task_id in self._task_queues:
                self._task_queues[task_id].put(data)
            
            # Call callback if provided
            if task.callback:
                task.callback(data)
            
            self.logger.info(f"Task completed: {task_id}")
        
        @self.socketio.on('pong', namespace='/agent')
        def handle_pong(data):
            sid = self._get_sid()
            for agent in self.agents.values():
                if agent.sid == sid:
                    agent.last_seen = time.time()
                    break
    
    def _get_sid(self) -> str:
        """Get current request's session ID."""
        from flask import request
        return request.sid
    
    def _remove_agent_by_sid(self, sid: str):
        """Remove agent by session ID."""
        to_remove = None
        for agent_id, agent in self.agents.items():
            if agent.sid == sid:
                to_remove = agent_id
                break
        
        if to_remove:
            del self.agents[to_remove]
            self.logger.info(f"Removed agent: {to_remove}")
    
    def get_available_agents(self) -> list[dict]:
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
        """Find an agent with the required capability."""
        for agent in self.agents.values():
            if agent.authenticated and capability in agent.capabilities:
                return agent
        return None
    
    def send_task(self, 
                  agent_id: str, 
                  command: str, 
                  params: dict,
                  callback: Callable = None,
                  timeout: float = 30.0) -> str:
        """Send a task to an agent."""
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
            callback=callback,
            timeout=timeout
        )
        self.pending_tasks[task_id] = task
        
        # Send task via WebSocket
        self.socketio.emit(
            'task',
            {
                'task_id': task_id,
                'command': command,
                'params': params
            },
            namespace='/agent',
            room=agent.sid
        )
        
        self.logger.info(f"Sent task {task_id} ({command}) to agent {agent_id}")
        return task_id
    
    def send_task_sync(self,
                       agent_id: str,
                       command: str,
                       params: dict,
                       timeout: float = 30.0) -> str:
        """Send a task and return task_id. Use wait_for_task to get result."""
        task_id = self.send_task(agent_id, command, params, timeout=timeout)
        
        # Create queue for this task
        self._task_queues[task_id] = Queue()
        
        return task_id
    
    def wait_for_task(self, task_id: str, timeout: float = 30.0) -> Optional[dict]:
        """Wait for a task to complete and return result."""
        if task_id not in self._task_queues:
            return None
        
        try:
            result = self._task_queues[task_id].get(timeout=timeout)
            return result
        except Empty:
            return None
        finally:
            # Cleanup
            if task_id in self._task_queues:
                del self._task_queues[task_id]
            if task_id in self.pending_tasks:
                del self.pending_tasks[task_id]
    
    def execute_snmp_get(self, 
                         target_ip: str, 
                         oid: str,
                         community: str = 'private',
                         agent_id: str = None) -> dict:
        """Execute SNMP GET via agent."""
        # Find suitable agent
        if agent_id is None:
            agent = self.get_agent_for_capability('snmp')
            if not agent:
                return {'success': False, 'error': 'No SNMP-capable agent available'}
            agent_id = agent.agent_id
        
        return self.send_task_sync(
            agent_id=agent_id,
            command='snmp_get',
            params={
                'target_ip': target_ip,
                'oid': oid,
                'community': community
            }
        )
    
    def execute_snmp_walk(self,
                          target_ip: str,
                          oid: str,
                          community: str = 'private',
                          agent_id: str = None) -> dict:
        """Execute SNMP WALK via agent."""
        if agent_id is None:
            agent = self.get_agent_for_capability('snmp')
            if not agent:
                return {'success': False, 'error': 'No SNMP-capable agent available'}
            agent_id = agent.agent_id
        
        return self.send_task_sync(
            agent_id=agent_id,
            command='snmp_walk',
            params={
                'target_ip': target_ip,
                'oid': oid,
                'community': community
            }
        )
    
    def ping_modem(self, target_ip: str, agent_id: str = None) -> dict:
        """Ping a modem via agent."""
        if agent_id is None:
            agent = self.get_agent_for_capability('snmp')
            if not agent:
                return {'success': False, 'error': 'No agent available'}
            agent_id = agent.agent_id
        
        return self.send_task_sync(
            agent_id=agent_id,
            command='ping',
            params={'target': target_ip}
        )


# Global agent manager instance
_agent_manager: Optional[AgentManager] = None


def get_agent_manager() -> Optional[AgentManager]:
    """Get the global agent manager instance."""
    return _agent_manager


def init_agent_websocket(app, auth_token: str = None):
    """Initialize agent WebSocket support."""
    global _agent_manager
    
    if not SOCKETIO_AVAILABLE:
        logger.warning("flask-socketio not available, agent support disabled")
        return None
    
    socketio = SocketIO(app, cors_allowed_origins="*")
    
    _agent_manager = AgentManager()
    if auth_token:
        _agent_manager.auth_token = auth_token
    
    _agent_manager.init_app(app, socketio)
    
    return socketio
