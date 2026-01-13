# PyPNM Remote Agent Integration
# SPDX-License-Identifier: Apache-2.0
#
# Files to copy into your PyPNM installation to enable remote agent support.
#
# Structure:
#   pypnm_integration/
#   ├── transport/
#   │   ├── __init__.py
#   │   ├── agent_manager.py      # Manages WebSocket connections
#   │   └── remote_transport.py   # SNMP/SSH via agent
#   ├── api/
#   │   └── agent_router.py       # FastAPI router
#   └── README.md
#
# Installation:
#   1. Copy transport/ to PyPNM/src/pypnm/transport/
#   2. Copy api/agent_router.py to PyPNM/src/pypnm/api/routers/
#   3. Register router in main.py (see below)
#   4. Update system.json configuration

from .transport import AgentManager, RemoteAgentTransport

__all__ = ['AgentManager', 'RemoteAgentTransport']
