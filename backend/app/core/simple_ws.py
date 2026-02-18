# PyPNM Web GUI - Simple WebSocket Agent Manager Stub
#
# Stub module for backward compatibility - routes agent requests via PyPNMClient

import os
import json
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SimpleAgent:
    """Simple agent proxy that sends tasks via HTTP to PyPNM API."""
    
    def __init__(self, agent_id: str = "pypnm-agent"):
        self.agent_id = agent_id
        self.pypnm_base_url = os.environ.get('PYPNM_BASE_URL', os.environ.get('PYPNM_API_URL', 'http://localhost:8000'))
    
    def send_task(self, task_type: str, params: dict, timeout: int = 60) -> Optional[dict]:
        """Send task to agent via PyPNM API."""
        try:
            url = f"{self.pypnm_base_url}/agent/task"
            payload = {
                "task_type": task_type,
                "params": params
            }
            
            logger.info(f"Sending task {task_type} to agent via {url}")
            response = requests.post(url, json=payload, timeout=timeout)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Agent task failed: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Agent task error: {e}")
            return None


class SimpleAgentManager:
    """Simple agent manager that provides agent access."""
    
    def __init__(self):
        self._agent = SimpleAgent()
    
    def get_agent_for_capability(self, capability: str) -> Optional[SimpleAgent]:
        """Return agent if it supports the capability."""
        # All capabilities supported by our single agent
        supported = [
            'pnm_us_get_interfaces',
            'cmts_snmp_direct',
            'pnm_utsc_configure',
            'pnm_utsc_start', 
            'pnm_us_rxmer_start',
            'snmp'
        ]
        if capability in supported:
            return self._agent
        return None


# Global instance
_agent_manager = None


def get_simple_agent_manager() -> SimpleAgentManager:
    """Get or create the simple agent manager."""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = SimpleAgentManager()
    return _agent_manager
