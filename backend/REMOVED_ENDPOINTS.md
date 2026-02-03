# Removed Endpoints - Phase 3 Migration

**Date**: 2026-02-03  
**Migration**: Old Agent Manager → PyPNM API

All endpoints listed below have been **permanently removed**. Use PyPNM API endpoints directly.

## Why Were These Removed?

The GUI backend duplicated functionality that already exists in PyPNM API. The new architecture routes all operations through PyPNM API, which automatically handles agent communication via `AgentSnmpTransport`.

**Old Architecture** (Removed):
```
Frontend → GUI Backend → Old Agent Manager → Agent → Device
```

**New Architecture** (Current):
```
Frontend → PyPNM API → AgentSnmpTransport → Agent → Device
```

---

## Removed Endpoints

### Agent Management

#### ❌ `GET /agents`
**Replacement**: `GET http://localhost:8000/api/agents`
```bash
# Old
curl http://localhost:5050/agents

# New
curl http://localhost:8000/api/agents
```

---

### Direct SNMP Operations

All direct SNMP operations are now handled automatically by PyPNM API via AgentSnmpTransport.

#### ❌ `POST /snmp/get`
**Replacement**: Use PyPNM API endpoints (SNMP is transparent)
```bash
# PyPNM API automatically routes SNMP through agent
# Just use the appropriate PyPNM endpoint
curl -X POST http://localhost:8000/docs/pnm/ds/status/getChannelStatus \
  -H "Content-Type: application/json" \
  -d '{"cable_modem": {"mac_address": "...", "ip_address": "..."}}'
```

#### ❌ `POST /snmp/set`
**Replacement**: PyPNM API handles SNMP operations

#### ❌ `POST /snmp/walk`
**Replacement**: PyPNM API handles SNMP operations

#### ❌ `POST /snmp/bulk_get`
**Replacement**: PyPNM API handles SNMP operations

---

### OFDM Operations

#### ❌ `POST /pnm/ofdm/tftp/configure`
**Replacement**: `POST /docs/pnm/common/tftp/setTftpServer`
```bash
curl -X POST http://localhost:8000/docs/pnm/common/tftp/setTftpServer \
  -H "Content-Type: application/json" \
  -d '{
    "cable_modem": {
      "mac_address": "00:11:22:33:44:55",
      "ip_address": "10.1.1.100",
      "snmp": {"snmpV2C": {"community": "private"}}
    },
    "tftp": {
      "ipv4": "172.22.147.18"
    }
  }'
```

#### ❌ `POST /pnm/ofdm/capture/trigger`
**Replacement**: `POST /docs/pnm/ds/ofdmChannelEstCoef/startCapture`

#### ❌ `POST /pnm/ofdm/channels`
**Replacement**: `POST /docs/pnm/ds/ofdmChannelEstCoef/getOfdmChannels`

#### ❌ `GET /pnm/ofdm/rxmer/<mac_address>`
**Replacement**: `POST /docs/pnm/ds/ofdmChannelEstCoef/getCaptureReport`

---

### PyPNM Operations

#### ❌ `GET /pypnm/health`
**Replacement**: `GET http://localhost:8000/`
```bash
curl http://localhost:8000/
```

#### ❌ `POST /pypnm/modem/<mac_address>/constellation`
**Replacement**: `POST /docs/pnm/ds/constellation/getConstellation`
```bash
curl -X POST http://localhost:8000/docs/pnm/ds/constellation/getConstellation \
  -H "Content-Type: application/json" \
  -d '{
    "cable_modem": {
      "mac_address": "00:11:22:33:44:55",
      "ip_address": "10.1.1.100",
      "snmp": {"snmpV2C": {"community": "private"}},
      "pnm_parameters": {"tftp": {"ipv4": "172.22.147.18"}}
    }
  }'
```

#### ❌ `POST /pypnm/modem/<mac_address>/pre-eq`
**Replacement**: `POST /docs/pnm/us/preEq/getPreEq`

#### ❌ `POST /pypnm/modem/<mac_address>/sysdescr`
**Replacement**: Use PyPNM system endpoints or direct SNMP

#### ❌ `POST /pypnm/modem/<mac_address>/event-log`
**Replacement**: `POST /docs/system/eventLog/getEventLog`

---

### System Information

#### ❌ `POST /modem/<mac_address>/uptime`
**Replacement**: Use PyPNM system status endpoints
```bash
curl -X POST http://localhost:8000/docs/system/status/getSystemStatus \
  -H "Content-Type: application/json" \
  -d '{"cable_modem": {"mac_address": "...", "ip_address": "..."}}'
```

---

## CMTS Operations

#### ✅ `GET /cmts/<hostname>/modems` - KEPT
This endpoint has been **kept** because it includes GUI-specific caching logic and Redis integration. However, it now uses PyPNM API internally via `PyPNMClient`.

---

## Migrated Endpoints

These endpoints were **updated** to use PyPNM API instead of being removed:

### ✅ `POST /pypnm/modem/<mac_address>/spectrum`
- Still exists, now uses `PyPNMClient.get_spectrum_analyzer()`
- Routes through PyPNM API automatically

### ✅ `POST /pypnm/modem/<mac_address>/fec`
- Still exists, now uses `PyPNMClient.get_fec_summary()`
- Routes through PyPNM API automatically

### ✅ `POST /pypnm/modem/<mac_address>/channel-stats`
- Still exists, now uses PyPNM channel status endpoints
- Routes through PyPNM API automatically

### ✅ `POST /modem/<mac_address>/system-info`
- Still exists, now uses PyPNM channel status endpoint
- Routes through PyPNM API automatically

---

## PyPNM API Documentation

**Full API Documentation**: http://localhost:8000/docs

**Key Endpoint Groups**:
- `/docs/pnm/ds/*` - Downstream PNM operations
- `/docs/pnm/us/*` - Upstream PNM operations
- `/docs/pnm/common/*` - Common operations (TFTP, etc.)
- `/docs/system/*` - System information
- `/api/agents` - Agent management

---

## Migration Examples

### Before (Removed):
```javascript
// Old GUI backend endpoint
fetch('/pypnm/modem/00:11:22:33:44:55/constellation', {
  method: 'POST',
  body: JSON.stringify({
    modem_ip: '10.1.1.100',
    community: 'private'
  })
})
```

### After (Current):
```javascript
// Direct PyPNM API call
fetch('http://localhost:8000/docs/pnm/ds/constellation/getConstellation', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    cable_modem: {
      mac_address: '00:11:22:33:44:55',
      ip_address: '10.1.1.100',
      snmp: {snmpV2C: {community: 'private'}},
      pnm_parameters: {tftp: {ipv4: '172.22.147.18'}}
    }
  })
})
```

---

## Benefits of This Change

1. **Single Source of Truth**: PyPNM API is authoritative
2. **Automatic Agent Routing**: AgentSnmpTransport handles everything
3. **Less Code**: No duplication between GUI backend and PyPNM API
4. **Better Documentation**: PyPNM API has OpenAPI/Swagger docs
5. **Easier Maintenance**: One codebase to maintain instead of two

---

## Need Help?

- **PyPNM API Docs**: http://localhost:8000/docs
- **Check Agent Status**: http://localhost:8000/api/agents
- **Test Endpoints**: Use PyPNM API's built-in Swagger UI at `/docs`
