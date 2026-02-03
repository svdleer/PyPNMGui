# PyPNM Remote Agent WebSocket Router
# SPDX-License-Identifier: Apache-2.0
#
# FastAPI router for remote agent WebSocket connections.
# Add to PyPNM: src/pypnm/api/routers/agent_ws.py
#
# Then include in your main app:
#   from pypnm.api.routers.agent_ws import router as agent_router
#   app.include_router(agent_router)

import os
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, HTTPException, Depends
from fastapi.responses import JSONResponse

from pypnm.transport.agent_manager import (
    AgentManager,
    configure_agent_manager,
    get_agent_manager
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Remote Agents"])

# Initialize agent manager with token from environment or config
_auth_token = os.environ.get("PYPNM_AGENT_TOKEN", "dev-token-change-me")
agent_manager = configure_agent_manager(_auth_token)


@router.websocket("/ws")
async def agent_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for remote agent connections.
    
    Agents connect here to receive commands from PyPNM.
    """
    await agent_manager.handle_websocket(websocket)


@router.get("/")
async def list_agents():
    """
    List all connected remote agents.
    
    Returns information about each connected agent including:
    - agent_id
    - capabilities
    - connection time
    - alive status
    """
    return {
        "agents": agent_manager.get_all_agents(),
        "total": len(agent_manager.agents)
    }


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get information about a specific agent."""
    agent = agent_manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    return {
        "agent_id": agent.agent_id,
        "capabilities": agent.capabilities,
        "connected_at": agent.connected_at,
        "is_alive": agent.is_alive
    }


@router.post("/{agent_id}/ping")
async def ping_agent(agent_id: str):
    """Send a ping to verify agent is responsive."""
    agent = agent_manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    try:
        result = await agent.execute(
            command="ping",
            params={},
            timeout=5
        )
        return {"status": "ok", "result": result}
    except TimeoutError:
        return {"status": "timeout", "message": "Agent did not respond"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/status/summary")
async def agent_status_summary():
    """Get summary of agent connectivity status."""
    agents = agent_manager.get_all_agents()
    alive_count = sum(1 for a in agents if a["is_alive"])
    
    return {
        "total_agents": len(agents),
        "alive_agents": alive_count,
        "has_connectivity": agent_manager.has_agents,
        "agents": [
            {"agent_id": a["agent_id"], "is_alive": a["is_alive"]}
            for a in agents
        ]
    }
