#!/bin/bash
# Test script for channel stats using SNMP table walks
# Run this on the remote server where dockers are running

MODEM_IP="${1:-10.206.234.83}"
COMMUNITY="${2:-z1gg0m0n1t0r1ng}"
TIMEOUT=5
RETRIES=1

echo "=============================================="
echo "Channel Stats Table Walk Test"
echo "=============================================="
echo "Modem IP: $MODEM_IP"
echo "Community: $COMMUNITY"
echo ""

# Tables to walk
declare -A TABLES
TABLES=(
    ["docsIfDownChannelTable"]="1.3.6.1.2.1.10.127.1.1.1"
    ["docsIfSigQTable"]="1.3.6.1.2.1.10.127.1.1.4"
    ["docsIfSigQExtTable"]="1.3.6.1.2.1.10.127.1.3.3"
    ["docsIf3SignalQualityExtTable"]="1.3.6.1.4.1.4491.2.1.20.1.24"
    ["docsIfUpChannelTable"]="1.3.6.1.2.1.10.127.1.1.2"
    ["docsIf3CmStatusUsTable"]="1.3.6.1.4.1.4491.2.1.20.1.2"
)

total_start=$(date +%s.%N)

for table_name in "${!TABLES[@]}"; do
    oid="${TABLES[$table_name]}"
    echo "----------------------------------------------"
    echo "Walking: $table_name"
    echo "OID: $oid"
    echo ""
    
    start=$(date +%s.%N)
    
    # Use snmpwalk with numeric OIDs for speed
    result=$(snmpwalk -v2c -c "$COMMUNITY" -t $TIMEOUT -r $RETRIES -On "$MODEM_IP" "$oid" 2>&1)
    
    end=$(date +%s.%N)
    elapsed=$(echo "$end - $start" | bc)
    
    # Count entries
    count=$(echo "$result" | grep -c "^\\.")
    
    echo "Entries: $count"
    echo "Time: ${elapsed}s"
    echo ""
    
    # Show first 5 entries as sample
    if [ "$count" -gt 0 ]; then
        echo "Sample (first 5):"
        echo "$result" | head -5
        echo ""
    else
        echo "No data or error:"
        echo "$result" | head -3
        echo ""
    fi
done

total_end=$(date +%s.%N)
total_elapsed=$(echo "$total_end - $total_start" | bc)

echo "=============================================="
echo "TOTAL TIME: ${total_elapsed}s"
echo "=============================================="
