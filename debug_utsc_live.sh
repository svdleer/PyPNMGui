#!/bin/bash
# Automated UTSC Live Debug Script

echo "========== UTSC LIVE MODE DEBUG =========="
echo "Timestamp: $(date)"
echo ""

MAC="e4:57:40:0b:db:b9"
CMTS_IP="172.16.6.212"
RF_PORT="1078534144"

echo "1. Testing UTSC start API..."
curl -s -X POST "http://localhost:5051/api/pypnm/upstream/utsc/start/${MAC}" \
  -H "Content-Type: application/json" \
  -d "{\"cmts_ip\":\"${CMTS_IP}\",\"rf_port_ifindex\":${RF_PORT},\"community\":\"Z1gg0Sp3c1@l\"}" | jq '.'
echo ""

echo "2. Checking TFTP directory for UTSC files..."
ssh -p 65001 access-engineering.nl "docker exec pypnm-gui-lab ls -lht /tftp/utsc_${MAC//:}* 2>/dev/null | head -10"
echo ""

echo "3. Checking backend logs for WebSocket activity..."
ssh -p 65001 access-engineering.nl "docker logs pypnm-gui-lab --tail 50 2>&1 | grep -i 'utsc\|websocket'"
echo ""

echo "4. Checking if UTSC is running on CMTS..."
ssh -p 65001 access-engineering.nl "docker exec pypnm-gui-lab snmpget -v2c -c Z1gg0Sp3c1@l ${CMTS_IP} 1.3.6.1.4.1.4998.1.1.20.2.32.1.19.${RF_PORT}"
echo ""

echo "5. Checking frontend JS version..."
ssh -p 65001 access-engineering.nl "docker exec pypnm-gui-lab grep -c 'Auto-restarting' /app/frontend/static/js/app.js"
echo "(Should be 0 - old code removed)"
echo ""

echo "6. Checking WebSocket route..."
ssh -p 65001 access-engineering.nl "docker exec pypnm-gui-lab grep -A5 'def utsc_websocket' /app/app/routes/ws_routes.py | head -10"
echo ""

echo "========== DEBUG COMPLETE =========="
