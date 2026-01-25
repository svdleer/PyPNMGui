#!/bin/bash
# Quick UTSC verification after CMTS reload

CMTS_IP="172.16.6.212"
RF_PORT="1078534144"
COMMUNITY="Z1gg0Sp3c1@l"

echo "=== CMTS UTSC Verification After Reload ==="
echo ""
echo "1. Testing SNMP connectivity..."
snmpget -v2c -c "$COMMUNITY" -t 2 "$CMTS_IP" sysUpTime.0
if [ $? -ne 0 ]; then
    echo "❌ SNMP not responding"
    exit 1
fi
echo "✓ SNMP working"
echo ""

echo "2. Checking UTSC row status..."
snmpget -v2c -c "$COMMUNITY" -t 2 "$CMTS_IP" 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.21.$RF_PORT.1
echo ""

echo "3. Triggering UTSC test via API..."
curl -s -X POST http://localhost:5050/api/pypnm/upstream/utsc/start/e4:57:40:0b:db:b9 \
  -H 'Content-Type: application/json' \
  -d '{
    "cmts_ip":"'$CMTS_IP'",
    "rf_port_ifindex":'$RF_PORT',
    "community":"'$COMMUNITY'",
    "tftp_ip":"172.16.6.101",
    "trigger_mode":2,
    "center_freq_hz":42500000,
    "span_hz":85000000,
    "num_bins":3200,
    "filename":"AFTER_RELOAD",
    "repeat_period_ms":100,
    "freerun_duration_ms":15000
  }' | python3 -m json.tool

echo ""
echo "4. Waiting 10 seconds for file generation..."
sleep 10

echo "5. Checking for generated files..."
FILE_COUNT=$(ls -1 /var/lib/tftpboot/AFTER_RELOAD_* 2>/dev/null | wc -l)
if [ $FILE_COUNT -gt 0 ]; then
    echo "✅ SUCCESS! $FILE_COUNT files generated:"
    ls -lh /var/lib/tftpboot/AFTER_RELOAD_* 2>/dev/null
else
    echo "❌ FAILED - No files generated"
    echo ""
    echo "Checking UTSC status..."
    snmpget -v2c -c "$COMMUNITY" -t 2 "$CMTS_IP" 1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1.1.$RF_PORT.1
fi
