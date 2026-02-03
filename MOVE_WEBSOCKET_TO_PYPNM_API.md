# Project: Move WebSocket Server from PyPNMGui to PyPNM API

## Objective
Move the agent WebSocket server from PyPNMGui to PyPNM API so that PyPNM can use the agent for SNMP operations directly.

## Current Architecture
```
Agent (pyPNMAgent) 
  ↓ WebSocket (ws://gui:5051/ws/agent)
PyPNMGui (Flask) - Agent Manager + Routes
  ↓ HTTP REST
PyPNM API (FastAPI) - CableModem does SNMP directly ❌
```

## Target Architecture
```
Agent (pyPNMAgent)
  ↓ WebSocket (ws://pypnm-api:8000/api/agents/ws)
PyPNM API (FastAPI) - Agent Manager + CableModem uses agent for SNMP ✅
  ↑ HTTP REST
PyPNMGui (Flask) - Just UI/routes
```

## Benefits
1. **PyPNM API owns SNMP operations** - All SNMP goes via agent
2. **Cleaner separation** - GUI is UI only, PyPNM handles PNM logic
3. **Agent integration at the source** - No proxy calls through GUI
4. **Better reusability** - PyPNM API can be used standalone with agent

## Components to Move

### 1. WebSocket Server & Agent Manager
**From:** `PyPNMGui/backend/app/core/simple_ws.py`
**To:** `PyPNM/src/pypnm/api/agent/` (new module)

Files to create in PyPNM:
- `src/pypnm/api/agent/__init__.py`
- `src/pypnm/api/agent/ws_server.py` - WebSocket endpoint
- `src/pypnm/api/agent/manager.py` - Agent connection manager
- `src/pypnm/api/agent/models.py` - Agent, Task data classes

### 2. Agent Routes
**From:** `PyPNMGui/backend/app/routes/ws_routes.py`
**To:** `PyPNM/src/pypnm/api/routes/agents/router.py`

API endpoints:
- `POST /api/agents/ws` - WebSocket connection
- `GET /api/agents` - List agents
- `GET /api/agents/{agent_id}` - Agent info
- `POST /api/agents/{agent_id}/task` - Send task to agent

### 3. Agent SNMP Transport
**From:** `PyPNMGui/pypnm_integration/transport/pypnm_agent_transport.py`
**To:** `PyPNM/src/pypnm/snmp/agent_transport.py`

This transport will be used by `CableModem` instead of direct UDP.

### 4. Agent Cable Modem
**From:** `PyPNMGui/pypnm_integration/agent_cable_modem.py`
**To:** PyPNM's `CableModem` will auto-detect and use agent transport

## Implementation Steps

### Phase 1: PyPNM API Changes
1. **Add agent module to PyPNM**
   ```bash
   cd /Users/silvester/PythonDev/Git/PyPNM
   mkdir -p src/pypnm/api/agent
   ```

2. **Copy & adapt WebSocket server**
   - Copy `simple_ws.py` → `src/pypnm/api/agent/manager.py`
   - Remove Flask dependencies, use FastAPI WebSocket
   - Add agent task queue management

3. **Add agent WebSocket route**
   - Create `src/pypnm/api/routes/agents/router.py`
   - Implement WebSocket endpoint for agent connections
   - Add agent status/list endpoints

4. **Create agent SNMP transport**
   - Copy `pypnm_agent_transport.py` → `src/pypnm/snmp/agent_transport.py`
   - Modify to use local agent manager instead of HTTP calls
   - Integrate with PyPNM's SNMP infrastructure

5. **Modify CableModem to use agent**
   - Add agent transport detection in `__load_snmp_version()`
   - Check if agent manager has connected agents
   - Use `AgentSnmpTransport` instead of `Snmp_v2c` when agent available

6. **Add environment variable**
   - `PYPNM_USE_AGENT_SNMP=true` - Enable agent SNMP routing

### Phase 2: PyPNMGui Changes
1. **Remove WebSocket server**
   - Keep minimal agent status display
   - Remove `simple_ws.py` agent manager

2. **Update routes to use PyPNM API**
   - `/api/agents` → proxy to `pypnm-api:8000/api/agents`
   - Remove agent task sending from GUI
   - Keep existing `/api/pypnm/measurements/` routes unchanged

3. **Update frontend**
   - Agent status fetched from PyPNM API
   - No changes to measurement calls

### Phase 3: Agent Configuration
1. **Update agent connection URL**
   ```python
   # agent_config.json
   {
     "pypnm_server_url": "ws://pypnm-api:8000/api/agents/ws",  # Changed from GUI
     ...
   }
   ```

2. **Docker compose update**
   ```yaml
   agent-lab:
     environment:
       - SERVER_URL=ws://localhost:8000/api/agents/ws  # Point to PyPNM API
   ```

### Phase 4: Testing
1. **Test agent connection to PyPNM API**
   ```bash
   # Check agent connects to PyPNM API
   curl http://localhost:8000/api/agents
   ```

2. **Test SNMP via agent**
   ```bash
   # Trigger RxMER - should use agent for SNMP
   curl -X POST http://localhost:8000/docs/pnm/ds/ofdm/rxmer/getCapture \
     -d '{"cable_modem": {...}}'
   ```

3. **Verify GUI still works**
   ```bash
   # GUI calls PyPNM API, which uses agent
   curl -X POST http://localhost:5050/api/pypnm/measurements/rxmer/9c:30:5b:f8:11:2b
   ```

## File Structure

### PyPNM (New)
```
PyPNM/
├── src/pypnm/
│   ├── api/
│   │   ├── agent/               # NEW
│   │   │   ├── __init__.py
│   │   │   ├── manager.py       # Agent connection manager
│   │   │   ├── models.py        # Agent, Task, Response models
│   │   │   └── ws_server.py     # WebSocket handler
│   │   └── routes/
│   │       └── agents/          # NEW
│   │           ├── __init__.py
│   │           └── router.py    # Agent API routes
│   └── snmp/
│       └── agent_transport.py   # NEW - Agent SNMP transport
```

### PyPNMGui (Modified)
```
PyPNMGui/
├── backend/app/
│   ├── core/
│   │   └── simple_ws.py         # REMOVE or keep minimal for display
│   └── routes/
│       ├── ws_routes.py         # REMOVE agent WebSocket
│       └── api_routes.py        # Add proxy to PyPNM agent endpoints
```

## Migration Strategy

### Option A: Big Bang (Risky)
- Move everything at once
- High risk of breaking

### Option B: Gradual Migration (Recommended)
1. **Step 1:** Add agent support to PyPNM API (backward compatible)
2. **Step 2:** Run both WebSocket servers (GUI + PyPNM API)
3. **Step 3:** Switch agent to PyPNM API WebSocket
4. **Step 4:** Test thoroughly
5. **Step 5:** Remove GUI WebSocket server

## Dependencies to Add to PyPNM

```toml
# pyproject.toml or requirements.txt
websockets>=12.0  # For WebSocket server
```

## Configuration Changes

### Docker Compose
```yaml
services:
  pypnm-api:
    environment:
      - PYPNM_USE_AGENT_SNMP=true
      - AGENT_WEBSOCKET_PORT=8000  # Use same port as API

  agent-lab:
    environment:
      - SERVER_URL=ws://localhost:8000/api/agents/ws  # Changed
```

### Agent Config
```json
{
  "agent_id": "lab-agent-local",
  "pypnm_server_url": "ws://localhost:8000/api/agents/ws",
  "auth_token": "your-token"
}
```

## Timeline Estimate
- **Phase 1 (PyPNM changes):** 2-3 days
- **Phase 2 (GUI changes):** 1 day  
- **Phase 3 (Agent config):** 1 hour
- **Phase 4 (Testing):** 1-2 days
- **Total:** ~5-7 days

## Success Criteria
- [x] Agent connects to PyPNM API WebSocket
- [x] PyPNM API routes SNMP through agent
- [x] All PNM measurements work via agent
- [x] GUI can query agent status from PyPNM API
- [x] No SNMP traffic bypasses agent
- [x] Backward compatibility maintained

## Rollback Plan
If issues arise:
1. Switch agent back to GUI WebSocket
2. Revert PyPNM API changes
3. Re-enable GUI agent manager

## Notes
- Keep PyPNMGui's `/api/snmp/get` routes as proxy to PyPNM API initially
- Monitor WebSocket connection stability
- Add reconnection logic to agent
- Consider adding health checks for agent connectivity
