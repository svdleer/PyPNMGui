# Phase 3 Migration Status

## Completed Actions

### 1. Removed Old Agent Manager Import
- ✅ Removed `from app.core.simple_ws import get_simple_agent_manager` from top-level imports
- ✅ Added `from app.core.pypnm_client import PyPNMClient` for PyPNM API access
- ✅ Removed `get_cm_capable_agent()` helper function

### 2. Migrated Functions

#### ✅ `pypnm_spectrum` (Line ~1359)
- **Before**: Called agent directly via `simple_ws`
- **After**: Uses `PyPNMClient.get_spectrum_analyzer()`
- **Result**: Routes through PyPNM API → AgentSnmpTransport → Agent

#### ✅ `pypnm_fec` (Line ~1397)
- **Before**: Called agent directly via `simple_ws`
- **After**: Uses `PyPNMClient.get_fec_summary()`
- **Result**: Routes through PyPNM API → AgentSnmpTransport → Agent

#### ✅ `pypnm_channel_stats` (Line ~1476)
- **Before**: Called agent directly via `simple_ws`
- **After**: Uses `PyPNMClient._post()` to channel status endpoints
- **Result**: Routes through PyPNM API → AgentSnmpTransport → Agent

#### ✅ `get_system_info` (Line ~207)
- **Before**: Called agent `pnm_channel_info` command
- **After**: Uses `PyPNMClient._post()` to channel status endpoint
- **Result**: Routes through PyPNM API → AgentSnmpTransport → Agent

### 3. Remaining Functions (Still Use Old Agent Manager)

These functions have **inline imports** of `simple_ws` and need individual migration:

#### Agent Management:
- `/agents` - GET - List connected agents
  → **Should query PyPNM API `/api/agents` instead**

#### SNMP Operations:
- `/snmp/set` - POST - Direct SNMP set
- `/snmp/get` - POST - Direct SNMP get  
- `/snmp/walk` - POST - Direct SNMP walk
- `/snmp/bulk_get` - POST - Direct SNMP bulk get
  → **PyPNM API handles SNMP automatically via AgentSnmpTransport**
  → **These are redundant - users should use PyPNM API endpoints directly**

#### OFDM Operations:
- `/pnm/ofdm/tftp/configure` - POST
- `/pnm/ofdm/capture/trigger` - POST
- `/pnm/ofdm/channels` - POST
- `/pnm/ofdm/rxmer/<mac_address>` - GET
  → **PyPNM API has OFDM endpoints**
  → **Should use `/docs/pnm/ds/ofdmChannelEstCoef/*` endpoints**

#### PyPNM Operations:
- `/pypnm/health` - GET
- `/pypnm/modem/<mac_address>/constellation` - POST
- `/pypnm/modem/<mac_address>/pre-eq` - POST
- `/pypnm/modem/<mac_address>/sysdescr` - POST
- `/pypnm/modem/<mac_address>/event-log` - POST
  → **These should call PyPNM API endpoints**

#### CMTS Operations:
- `/cmts/<hostname>/modems` - GET
  → **Can use PyPNM API or keep for GUI-specific caching logic**

## Migration Strategy

### Option A: Complete Removal (Recommended)
Delete all remaining functions that use `simple_ws` and document that clients should use PyPNM API directly.

**Rationale**:
- PyPNM API is the authoritative source
- Agent routing is transparent via AgentSnmpTransport
- GUI should be a thin client, not duplicate API functionality
- Reduces maintenance burden

**Impact**:
- Frontend may need updates to call PyPNM API directly
- Simpler backend architecture
- Cleaner separation of concerns

### Option B: Proxy Pattern (Keep for Compatibility)
Keep functions but make them simple proxies to PyPNM API.

**Rationale**:
- Backward compatibility for frontend
- No frontend changes needed
- Gradual migration path

**Impact**:
- More code to maintain
- Duplication of logic
- Unclear which layer is authoritative

## Recommended Next Steps

### Immediate (Complete Phase 3):
1. **Remove all functions with inline `simple_ws` imports**
2. **Document removed endpoints** in API changelog
3. **Update frontend** to use PyPNM API endpoints directly
4. **Delete `simple_ws.py`** and `agent_manager.py`
5. **Remove `ws_routes.py`** (old agent WebSocket server)

### Commands to Execute:

```bash
# 1. Create list of removed endpoints
cat > backend/REMOVED_ENDPOINTS.md << 'EOF'
# Removed Endpoints - Phase 3 Migration

All these endpoints have been removed. Use PyPNM API endpoints instead.

## Agent Management
- GET `/agents` → Use PyPNM API `GET /api/agents`

## SNMP Operations (Use PyPNM API)
- POST `/snmp/set` → PyPNM handles automatically
- POST `/snmp/get` → PyPNM handles automatically
- POST `/snmp/walk` → PyPNM handles automatically
- POST `/snmp/bulk_get` → PyPNM handles automatically

## OFDM Operations (Use PyPNM API)
- POST `/pnm/ofdm/tftp/configure` → `POST /docs/pnm/common/tftp/*`
- POST `/pnm/ofdm/capture/trigger` → `POST /docs/pnm/ds/ofdmChannelEstCoef/*`
- POST `/pnm/ofdm/channels` → `POST /docs/pnm/ds/ofdmChannelEstCoef/*`
- GET `/pnm/ofdm/rxmer/<mac>` → `POST /docs/pnm/ds/ofdmChannelEstCoef/getCaptureReport`

## PyPNM Operations (Use PyPNM API)
- GET `/pypnm/health` → `GET /`
- POST `/pypnm/modem/<mac>/constellation` → `POST /docs/pnm/ds/constellation/*`
- POST `/pypnm/modem/<mac>/pre-eq` → `POST /docs/pnm/us/preEq/*`
- POST `/pypnm/modem/<mac>/sysdescr` → PyPNM SNMP operations
- POST `/pypnm/modem/<mac>/event-log` → `POST /docs/system/eventLog/*`

All PyPNM API endpoints are documented at: http://localhost:8000/docs
EOF

# 2. Remove the functions (create backup first)
cp backend/app/routes/api_routes.py backend/app/routes/api_routes.py.backup

# 3. Delete old agent manager files
git rm backend/app/core/simple_ws.py
git rm backend/app/core/agent_manager.py
git rm backend/app/routes/ws_routes.py

# 4. Commit
git add -A
git commit -m "Phase 3 COMPLETE: Remove all old agent manager code

BREAKING CHANGES:
- Removed 15 legacy endpoints that used old agent manager
- Deleted simple_ws.py, agent_manager.py, ws_routes.py
- All operations now route through PyPNM API

Migration Guide:
- Use PyPNM API endpoints directly (http://localhost:8000/docs)
- Agent routing is automatic via AgentSnmpTransport
- See backend/REMOVED_ENDPOINTS.md for migration paths

Architecture:
Frontend → PyPNM API → AgentSnmpTransport → Agent → Device"
```

## Current Status

**Migrated (4/19 functions):**
- ✅ pypnm_spectrum
- ✅ pypnm_fec
- ✅ pypnm_channel_stats
- ✅ get_system_info

**Remaining (15/19 functions):**
- ⏳ All have inline `simple_ws` imports
- ⏳ All are candidates for removal
- ⏳ All have PyPNM API equivalents

## Decision Required

**Do you want to:**
A. **Complete removal** - Delete all 15 remaining functions + old agent manager files
B. **Proxy pattern** - Keep functions but make them call PyPNM API
C. **Hybrid** - Remove some, proxy others based on usage

**Recommendation**: **Option A** - Clean break, simpler architecture, forces proper PyPNM API usage.
