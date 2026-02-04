# PyPNM SNMP Routing Test Plan

**Date:** February 4, 2026  
**Objective:** Verify that ALL SNMP requests are routed through PyPNMAgent, with NO direct SNMP from GUI or PyPNM API

## Architecture Overview

```
┌─────────────┐ HTTP/REST  ┌──────────────┐ WebSocket  ┌──────────────┐ SNMP
│  PyPNM GUI  ├───────────►│  PyPNM API   ├───────────►│ PyPNM Agent  ├────────► CMTS/Modems
│ (Flask)     │            │  (FastAPI)   │            │  (Remote)    │     UDP 161
└─────────────┘            └──────────────┘            └──────────────┘
     ❌ NO SNMP                 ❌ NO SNMP                  ✅ ONLY HERE
```

## Current Configuration

✅ **Agent Status:** Connected & Authenticated  
✅ **Agent ID:** `lab-agent-local`  
✅ **API Config:** `PYPNM_USE_AGENT_SNMP=true`  
✅ **Agent Capabilities:** All SNMP operations enabled

## Test Plan

### Pre-Test: Network Capture Setup

Start packet capture on remote server to monitor SNMP traffic:

```bash
# On remote server (access-engineering.nl)
# Capture SNMP traffic from all containers/processes
sudo tcpdump -i any -w /tmp/pypnm_snmp_test.pcap \
  'udp port 161 or udp port 162' &
TCPDUMP_PID=$!
```

### Test 1: Get CMTS List
**Action:** Load GUI main page with CMTS list  
**Expected SNMP Source:** PyPNMAgent container only  
**Expected API Flow:**
1. Browser → GUI: `GET /`
2. GUI → PyPNM API: `GET /api/pypnm/cmts`
3. API → Agent (WebSocket): `{"command": "cmts_get_list", ...}`
4. Agent → CMTS: SNMP GET requests
5. Agent → API: Response via WebSocket
6. API → GUI: JSON response
7. GUI → Browser: HTML page

**Test Command:**
```bash
curl -s http://access-engineering.nl:5050/ | grep -i cmts
```

### Test 2: Get Modem List
**Action:** Query modems for a specific CMTS  
**Expected SNMP Source:** PyPNMAgent only  
**Expected Flow:**
1. GUI → API: `GET /api/pypnm/cmts/{cmts_ip}/modems`
2. API → Agent: `{"command": "cmts_get_modems", ...}`
3. Agent → CMTS: SNMP WALK
4. Return via WebSocket chain

**Test Command:**
```bash
curl -s http://access-engineering.nl:5050/api/pypnm/cmts/172.16.6.212/modems
```

### Test 3: Get Modem Details
**Action:** Query specific modem information  
**Expected SNMP Source:** PyPNMAgent only  
**Expected Flow:**
1. GUI → API: `GET /api/pypnm/modem/{mac}`
2. API → Agent: `{"command": "get_modem_info", ...}`
3. Agent → CMTS + Modem: Multiple SNMP queries
4. Return enriched data

**Test Command:**
```bash
# Use a known modem MAC from the lab
curl -s http://access-engineering.nl:5050/api/pypnm/modem/00:01:02:03:04:05
```

### Test 4: OFDM Channel Data
**Action:** Query OFDM channel information  
**Expected SNMP Source:** PyPNMAgent only  
**Expected Flow:**
1. GUI → API: `GET /api/pypnm/modem/{mac}/ofdm`
2. API → Agent: `{"command": "pnm_ofdm_channels", ...}`
3. Agent → Modem: SNMP GET/WALK for OFDM OIDs
4. Return channel data

### Test 5: PNM Spectrum Capture
**Action:** Trigger spectrum analyzer capture  
**Expected SNMP Source:** PyPNMAgent only  
**Expected Flow:**
1. GUI → API: `POST /api/pypnm/modem/{mac}/spectrum`
2. API → Agent: `{"command": "pnm_spectrum", ...}`
3. Agent → Modem: SNMP SET + GET sequence
4. Agent → TFTP: File retrieval
5. Return spectrum data

### Test 6: Cache Operations
**Action:** Test Redis cache endpoints  
**Expected:** NO SNMP (cache only)  
**Test Commands:**
```bash
# Cache stats
curl -s http://access-engineering.nl:5050/cache/stats

# Flush modem cache
curl -X POST http://access-engineering.nl:5050/cache/flush/modems
```

## Post-Test: Analyze Captured Traffic

```bash
# Stop packet capture
sudo kill $TCPDUMP_PID

# Analyze captured SNMP packets
sudo tcpdump -r /tmp/pypnm_snmp_test.pcap -nn | grep 'UDP.*161\|UDP.*162'

# Check source IPs
sudo tcpdump -r /tmp/pypnm_snmp_test.pcap -nn 'udp port 161' | \
  awk '{print $3}' | sort -u

# Expected: Only agent container/host IP
# NOT expected: GUI container IP, API container IP
```

## Verification Checklist

- [ ] Agent is connected and authenticated
- [ ] PyPNM API `PYPNM_USE_AGENT_SNMP=true`
- [ ] GUI can load and display CMTS list
- [ ] GUI can load and display modem list
- [ ] GUI can show modem details
- [ ] OFDM channel data displays correctly
- [ ] All SNMP packets originate from agent container/host
- [ ] NO SNMP packets from GUI container
- [ ] NO SNMP packets from API container
- [ ] WebSocket communication between API and Agent working
- [ ] Cache endpoints respond correctly

## Success Criteria

✅ **ALL tests pass**  
✅ **100% of SNMP traffic originates from PyPNMAgent**  
✅ **0 SNMP packets from GUI or API containers**  
✅ **All GUI functionality works normally**

## Failure Scenarios

❌ **SNMP from GUI:** Direct SNMP code still in Flask app  
❌ **SNMP from API:** PyPNM not using agent transport  
❌ **No data in GUI:** Agent WebSocket communication broken  
❌ **Errors in logs:** Authentication or routing issues

## Rollback Plan

If agent routing is broken:
1. Set `PYPNM_USE_AGENT_SNMP=false` in API environment
2. Restart API container
3. PyPNM will fall back to direct SNMP
4. Debug agent communication issue

## Additional Monitoring

**During tests, monitor these logs:**

```bash
# Agent logs (should show SNMP activity)
ssh access-engineering.nl "docker logs -f pypnm-agent-lab"

# API logs (should show agent WebSocket messages)
ssh access-engineering.nl "docker logs -f pypnm-api"

# GUI logs (should show HTTP requests only)
ssh access-engineering.nl "docker logs -f pypnm-gui-lab"
```

---

## Quick Test Script

```bash
#!/bin/bash
# Quick SNMP routing validation

echo "🔍 Testing PyPNM SNMP Routing..."
echo ""

# Start capture in background
ssh -p 65001 svdleer@access-engineering.nl \
  "sudo timeout 30 tcpdump -i any -w /tmp/snmp_test.pcap 'udp port 161' 2>/dev/null &"

sleep 2

# Test 1: Get CMTS list (triggers SNMP)
echo "Test 1: CMTS List"
curl -s http://access-engineering.nl:8000/api/pypnm/cmts > /dev/null && echo "✅ API responded" || echo "❌ Failed"

sleep 2

# Test 2: Get modem list (triggers SNMP WALK)
echo "Test 2: Modem List"  
curl -s http://access-engineering.nl:8000/api/pypnm/cmts/172.16.6.212/modems > /dev/null && echo "✅ API responded" || echo "❌ Failed"

sleep 2

# Wait for capture to complete
sleep 5

# Analyze
echo ""
echo "📊 Analyzing SNMP traffic..."
ssh -p 65001 svdleer@access-engineering.nl \
  "sudo tcpdump -r /tmp/snmp_test.pcap -nn 2>/dev/null | grep -c 'UDP.*161' | xargs echo 'SNMP packets:'"

echo ""
echo "✅ Test complete. Check packet capture for source IPs."
```
