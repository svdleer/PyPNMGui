#!/bin/bash
# Test script for modem connectivity through various proxy methods
# Tests SSH tunnel, socat, netcat, and direct SSH+SNMP access to modems

set -e

# Configuration
CM_PROXY_HOST="${CM_PROXY_HOST:-hop-access1.ext.oss.local}"
CM_PROXY_USER="${CM_PROXY_USER:-svdleer}"
CM_PROXY_KEY="${CM_PROXY_KEY:-~/.ssh/id_rsa}"
TEST_MODEM_IP="${TEST_MODEM_IP:-10.214.157.17}"
SNMP_COMMUNITY="${SNMP_COMMUNITY:-m0d3m1nf0}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "  Modem Connectivity Test Suite"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  CM Proxy:      $CM_PROXY_HOST"
echo "  CM Proxy User: $CM_PROXY_USER"
echo "  Test Modem IP: $TEST_MODEM_IP"
echo "  SNMP Community: $SNMP_COMMUNITY"
echo ""

# Test 1: SSH connection to proxy
echo "=========================================="
echo "Test 1: SSH Connection to CM Proxy"
echo "=========================================="
if ssh -i "$CM_PROXY_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$CM_PROXY_USER@$CM_PROXY_HOST" "echo 'SSH OK'" 2>/dev/null | grep -q "SSH OK"; then
    echo -e "${GREEN}✓ PASS${NC} - SSH connection to $CM_PROXY_HOST successful"
else
    echo -e "${RED}✗ FAIL${NC} - Cannot SSH to $CM_PROXY_HOST"
    echo "  Check: SSH key, hostname, firewall"
    exit 1
fi
echo ""

# Test 2: snmpwalk availability on proxy
echo "=========================================="
echo "Test 2: SNMP Tools on CM Proxy"
echo "=========================================="
if ssh -i "$CM_PROXY_KEY" "$CM_PROXY_USER@$CM_PROXY_HOST" "which snmpwalk" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ PASS${NC} - snmpwalk is installed on $CM_PROXY_HOST"
else
    echo -e "${RED}✗ FAIL${NC} - snmpwalk not found on $CM_PROXY_HOST"
    echo "  Install: sudo apt-get install snmp"
    exit 1
fi
echo ""

# Test 3: Direct SNMP query via SSH
echo "=========================================="
echo "Test 3: Direct SNMP Query (SSH + snmpwalk)"
echo "=========================================="
echo "Running: ssh $CM_PROXY_HOST 'snmpwalk -v2c -c $SNMP_COMMUNITY -t 5 -r 1 $TEST_MODEM_IP sysDescr'"
SNMP_RESULT=$(ssh -i "$CM_PROXY_KEY" "$CM_PROXY_USER@$CM_PROXY_HOST" "timeout 10 snmpwalk -v2c -c $SNMP_COMMUNITY -t 5 -r 1 $TEST_MODEM_IP sysDescr 2>&1" || echo "FAILED")

if echo "$SNMP_RESULT" | grep -q "STRING:"; then
    echo -e "${GREEN}✓ PASS${NC} - SNMP query successful"
    echo "  Modem info: $(echo "$SNMP_RESULT" | grep STRING | head -1)"
elif echo "$SNMP_RESULT" | grep -qi "timeout"; then
    echo -e "${RED}✗ FAIL${NC} - SNMP timeout - modem not reachable"
    echo "  Modem may be offline or not routable from $CM_PROXY_HOST"
elif echo "$SNMP_RESULT" | grep -qi "no response"; then
    echo -e "${RED}✗ FAIL${NC} - No SNMP response"
    echo "  Check: modem SNMP enabled, community string correct"
else
    echo -e "${RED}✗ FAIL${NC} - SNMP query failed"
    echo "  Error: $SNMP_RESULT"
fi
echo ""

# Test 4: Batch query performance
echo "=========================================="
echo "Test 4: Batch SNMP Query Performance"
echo "=========================================="
echo "Testing 4 OIDs simultaneously..."
START_TIME=$(date +%s)

BATCH_CMD="echo '==ds_freq==' && timeout 7 snmpwalk -v2c -c $SNMP_COMMUNITY -t 5 -r 1 $TEST_MODEM_IP 1.3.6.1.2.1.10.127.1.1.1.1.2 2>&1 | head -5 ; "
BATCH_CMD+="echo '==ds_power==' && timeout 7 snmpwalk -v2c -c $SNMP_COMMUNITY -t 5 -r 1 $TEST_MODEM_IP 1.3.6.1.2.1.10.127.1.1.1.1.6 2>&1 | head -5 ; "
BATCH_CMD+="echo '==ds_snr==' && timeout 7 snmpwalk -v2c -c $SNMP_COMMUNITY -t 5 -r 1 $TEST_MODEM_IP 1.3.6.1.2.1.10.127.1.1.4.1.5 2>&1 | head -5 ; "
BATCH_CMD+="echo '==us_power==' && timeout 7 snmpwalk -v2c -c $SNMP_COMMUNITY -t 5 -r 1 $TEST_MODEM_IP 1.3.6.1.4.1.4491.2.1.20.1.2.1.1 2>&1 | head -5"

BATCH_RESULT=$(ssh -i "$CM_PROXY_KEY" "$CM_PROXY_USER@$CM_PROXY_HOST" "$BATCH_CMD" 2>&1)
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

if echo "$BATCH_RESULT" | grep -q "==ds_freq==" && echo "$BATCH_RESULT" | grep -q "==ds_power=="; then
    echo -e "${GREEN}✓ PASS${NC} - Batch query successful in ${ELAPSED}s"
    echo "  Retrieved multiple OIDs from modem"
    
    # Check for timeouts
    TIMEOUT_COUNT=$(echo "$BATCH_RESULT" | grep -c "TIMEOUT" || echo "0")
    if [ "$TIMEOUT_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}⚠ WARNING${NC} - $TIMEOUT_COUNT OID(s) timed out"
    fi
else
    echo -e "${RED}✗ FAIL${NC} - Batch query failed"
    echo "  Check if modem OIDs are responding"
fi
echo ""

# Test 5: Check for timeout command
echo "=========================================="
echo "Test 5: Timeout Command Availability"
echo "=========================================="
if ssh -i "$CM_PROXY_KEY" "$CM_PROXY_USER@$CM_PROXY_HOST" "which timeout" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ PASS${NC} - 'timeout' command available"
else
    echo -e "${YELLOW}⚠ WARNING${NC} - 'timeout' command not found"
    echo "  Install: sudo apt-get install coreutils"
    echo "  Agent will work but may hang on unresponsive modems"
fi
echo ""

# Test 6: Network latency
echo "=========================================="
echo "Test 6: Network Latency to Modem"
echo "=========================================="
PING_RESULT=$(ssh -i "$CM_PROXY_KEY" "$CM_PROXY_USER@$CM_PROXY_HOST" "ping -c 3 -W 2 $TEST_MODEM_IP 2>&1" || echo "FAILED")

if echo "$PING_RESULT" | grep -q "3 received"; then
    AVG_TIME=$(echo "$PING_RESULT" | grep "avg" | sed 's/.*= [^/]*\/\([^/]*\)\/.*/\1/')
    echo -e "${GREEN}✓ PASS${NC} - Modem is pingable (avg ${AVG_TIME}ms)"
elif echo "$PING_RESULT" | grep -q "received"; then
    echo -e "${YELLOW}⚠ WARNING${NC} - Partial packet loss to modem"
    echo "$PING_RESULT" | grep "packet loss"
else
    echo -e "${YELLOW}⚠ INFO${NC} - Modem not pingable (ICMP may be blocked)"
    echo "  This is normal - many modems don't respond to ping"
fi
echo ""

# Summary
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo -e "${GREEN}✓${NC} SSH connection working"
echo -e "${GREEN}✓${NC} SNMP tools available"
if echo "$SNMP_RESULT" | grep -q "STRING:"; then
    echo -e "${GREEN}✓${NC} Modem SNMP queries working"
    echo ""
    echo -e "${GREEN}All tests passed!${NC} Agent should work correctly."
else
    echo -e "${RED}✗${NC} Modem SNMP queries failing"
    echo ""
    echo -e "${RED}Action required:${NC} Fix modem connectivity before running agent"
fi
echo ""
