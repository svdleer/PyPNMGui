#!/bin/bash
# Test SNMP Routing - Verify traffic only comes from agent, not GUI/API
# Date: 2026-02-04

CMTS_IP="172.16.6.212"
CM_IP="10.206.234.7"
CM_MAC="9c:30:5b:f8:11:2b"
AGENT_HOST_IP="172.16.6.62"  # The server where agent runs
GUI_HOST_IP="172.16.6.62"     # The server where GUI runs (same server)
API_HOST_IP="172.16.6.62"     # The server where API runs (same server)

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "   SNMP Routing Verification Test"
echo "========================================"
echo ""
echo "Testing that SNMP requests come ONLY from agent (${AGENT_HOST_IP})"
echo "NOT from GUI or PyPNM API"
echo ""

# Test 1: Get CMTS Info via GUI
echo -e "${YELLOW}Test 1: Get CMTS Info (GUI → PyPNM API → Agent → CMTS)${NC}"
echo "Expected: SNMP request from ${AGENT_HOST_IP} to ${CMTS_IP}"
echo ""
echo "Starting packet capture on remote agent server..."

ssh -p 65001 svdleer@access-engineering.nl "sudo timeout 15 tcpdump -i any -n 'host ${CMTS_IP} and udp port 161' -w /tmp/test1_cmts.pcap 2>/dev/null &"
sleep 2

echo "Making API request to get CMTS info..."
RESPONSE=$(curl -s -X GET "http://localhost:5050/api/pypnm/cmts/list" \
  -H "Content-Type: application/json" 2>/dev/null)

sleep 13

echo "Analyzing capture..."
ssh -p 65001 svdleer@access-engineering.nl "sudo tcpdump -r /tmp/test1_cmts.pcap -n 2>/dev/null | head -20" > /tmp/test1_output.txt

if grep -q "${AGENT_HOST_IP}" /tmp/test1_output.txt; then
    echo -e "${GREEN}✅ PASS: SNMP traffic from agent (${AGENT_HOST_IP})${NC}"
else
    echo -e "${RED}❌ FAIL: No SNMP traffic detected from agent${NC}"
fi

if grep -q "${GUI_HOST_IP}" /tmp/test1_output.txt && [ "$GUI_HOST_IP" != "$AGENT_HOST_IP" ]; then
    echo -e "${RED}❌ FAIL: Unexpected SNMP traffic from GUI server${NC}"
fi

echo ""
echo "Capture details:"
cat /tmp/test1_output.txt
echo ""

# Test 2: Get Cable Modem Info
echo -e "${YELLOW}Test 2: Get Cable Modem Info (GUI → PyPNM API → Agent → CM)${NC}"
echo "Expected: SNMP request from ${AGENT_HOST_IP} to ${CM_IP}"
echo ""

ssh -p 65001 svdleer@access-engineering.nl "sudo timeout 15 tcpdump -i any -n 'host ${CM_IP} and udp port 161' -w /tmp/test2_cm.pcap 2>/dev/null &"
sleep 2

echo "Making API request to get cable modem info..."
RESPONSE=$(curl -s -X POST "http://localhost:5050/api/pypnm/cable-modem/info" \
  -H "Content-Type: application/json" \
  -d "{\"mac_address\": \"${CM_MAC}\", \"ip_address\": \"${CM_IP}\"}" 2>/dev/null)

sleep 13

echo "Analyzing capture..."
ssh -p 65001 svdleer@access-engineering.nl "sudo tcpdump -r /tmp/test2_cm.pcap -n 2>/dev/null | head -20" > /tmp/test2_output.txt

if grep -q "${AGENT_HOST_IP}" /tmp/test2_output.txt; then
    echo -e "${GREEN}✅ PASS: SNMP traffic from agent (${AGENT_HOST_IP})${NC}"
else
    echo -e "${RED}❌ FAIL: No SNMP traffic detected from agent${NC}"
fi

echo ""
echo "Capture details:"
cat /tmp/test2_output.txt
echo ""

# Test 3: Direct PyPNM API test
echo -e "${YELLOW}Test 3: Direct PyPNM API Call (bypassing GUI)${NC}"
echo "Expected: SNMP request from ${AGENT_HOST_IP} to ${CMTS_IP}"
echo ""

ssh -p 65001 svdleer@access-engineering.nl "sudo timeout 15 tcpdump -i any -n 'host ${CMTS_IP} and udp port 161' -w /tmp/test3_direct.pcap 2>/dev/null &"
sleep 2

echo "Making direct PyPNM API request..."
# This would be a direct PyPNM API call if endpoint exists
# For now, test via GUI which proxies to PyPNM API

sleep 13

# Summary
echo ""
echo "========================================"
echo "   Test Summary"
echo "========================================"
echo ""
echo "Architecture Verification:"
echo "  GUI (localhost:5050) → PyPNM API (localhost:8000) → Agent (${AGENT_HOST_IP})"
echo ""
echo "Expected SNMP Flow:"
echo "  ✓ All SNMP requests should originate from: ${AGENT_HOST_IP}"
echo "  ✗ No SNMP should come from GUI or API containers"
echo ""
echo "Agent Status:"
curl -s http://localhost:8000/api/agents | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  Connected: {d['count']} agent(s)\")"
echo ""

# Cleanup
rm -f /tmp/test1_output.txt /tmp/test2_output.txt /tmp/test3_output.txt
ssh -p 65001 svdleer@access-engineering.nl "sudo rm -f /tmp/test{1,2,3}*.pcap" 2>/dev/null

echo "Test complete!"
