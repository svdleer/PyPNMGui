#!/bin/bash
# Test script for channel stats using SNMP table walks
# Walks both Modem and CMTS tables
# Run this on the remote server where dockers are running

MODEM_IP="${1:-10.206.234.92}"
MODEM_MAC="${2:-90:32:4b:c8:19:0b}"
CMTS_IP="${3:-172.16.6.212}"
CM_COMMUNITY="${4:-z1gg0m0n1t0r1ng}"
CMTS_COMMUNITY="${5:-public}"
TIMEOUT=5
RETRIES=1

echo "=============================================="
echo "Channel Stats Table Walk Test (CM + CMTS)"
echo "=============================================="
echo "Modem IP: $MODEM_IP"
echo "Modem MAC: $MODEM_MAC"
echo "CMTS IP: $CMTS_IP"
echo "CM Community: $CM_COMMUNITY"
echo "CMTS Community: $CMTS_COMMUNITY"
echo ""

total_start=$(date +%s.%N)

echo "############################################"
echo "# MODEM TABLES"
echo "############################################"
echo ""

# CM Tables to walk
declare -A CM_TABLES
CM_TABLES=(
    ["docsIfDownChannelTable"]="1.3.6.1.2.1.10.127.1.1.1"
    ["docsIfSigQTable"]="1.3.6.1.2.1.10.127.1.1.4"
    ["docsIf3SignalQualityExtTable"]="1.3.6.1.4.1.4491.2.1.20.1.24"
    ["docsIfUpChannelTable"]="1.3.6.1.2.1.10.127.1.1.2"
    ["docsIf3CmStatusUsTable"]="1.3.6.1.4.1.4491.2.1.20.1.2"
)

for table_name in "${!CM_TABLES[@]}"; do
    oid="${CM_TABLES[$table_name]}"
    echo "----------------------------------------------"
    echo "Walking: $table_name (CM)"
    echo "OID: $oid"
    
    start=$(date +%s.%N)
    result=$(snmpwalk -v2c -c "$CM_COMMUNITY" -t $TIMEOUT -r $RETRIES -On "$MODEM_IP" "$oid" 2>&1)
    end=$(date +%s.%N)
    elapsed=$(echo "$end - $start" | bc)
    
    count=$(echo "$result" | grep -c "^\\.")
    
    echo "Entries: $count | Time: ${elapsed}s"
    
    if [ "$count" -gt 0 ]; then
        echo "Sample (first 3):"
        echo "$result" | head -3
    else
        echo "No data: $(echo "$result" | head -1)"
    fi
    echo ""
done

echo ""
echo "############################################"
echo "# CMTS TABLES (for modem $MODEM_MAC)"
echo "############################################"
echo ""

# CMTS Tables to walk
declare -A CMTS_TABLES
CMTS_TABLES=(
    # Per-CM upstream status (RX power, SNR, timing, microreflections)
    ["docsIf3CmtsCmUsStatusTable"]="1.3.6.1.4.1.4491.2.1.20.1.4"
    # CM registration status (to find CM reg ID from MAC)
    ["docsIf3CmtsCmRegStatusTable"]="1.3.6.1.4.1.4491.2.1.20.1.3"
    # Legacy CM status
    ["docsIfCmtsCmStatusTable"]="1.3.6.1.2.1.10.127.1.3.3"
    # Signal quality per CM
    ["docsIfCmtsSignalQualityTable"]="1.3.6.1.2.1.10.127.1.1.4"
)

# Convert MAC to decimal format for OID (aa:bb:cc:dd:ee:ff -> 170.187.204.221.238.255)
MAC_DECIMAL=$(python3 -c "mac='$MODEM_MAC'; print('.'.join(str(int(x,16)) for x in mac.split(':')))")
echo "MAC in decimal: $MAC_DECIMAL"
echo ""

for table_name in "${!CMTS_TABLES[@]}"; do
    oid="${CMTS_TABLES[$table_name]}"
    echo "----------------------------------------------"
    echo "Walking: $table_name (CMTS)"
    echo "OID: $oid"
    
    start=$(date +%s.%N)
    # For CMTS tables, we do a full walk but grep for our MAC
    result=$(snmpwalk -v2c -c "$CMTS_COMMUNITY" -t $TIMEOUT -r $RETRIES -On "$CMTS_IP" "$oid" 2>&1)
    end=$(date +%s.%N)
    elapsed=$(echo "$end - $start" | bc)
    
    total_count=$(echo "$result" | grep -c "^\\.")
    
    # Filter for our specific modem (MAC appears in index)
    if [ "$total_count" -gt 0 ]; then
        modem_entries=$(echo "$result" | grep -i "$MAC_DECIMAL" || echo "")
        modem_count=$(echo "$modem_entries" | grep -c "^\\." 2>/dev/null || echo "0")
    else
        modem_entries=""
        modem_count=0
    fi
    
    echo "Total entries: $total_count | For this modem: $modem_count | Time: ${elapsed}s"
    
    if [ -n "$modem_entries" ] && [ "$modem_count" -gt 0 ]; then
        echo "Entries for $MODEM_MAC:"
        echo "$modem_entries" | head -10
    elif [ "$total_count" -gt 0 ]; then
        echo "Sample (first 3 from table):"
        echo "$result" | head -3
    else
        echo "No data: $(echo "$result" | head -1)"
    fi
    echo ""
done

# Also try to find CM reg ID
echo "----------------------------------------------"
echo "Looking up CM Registration ID..."
echo ""

# docsIf3CmtsCmRegStatusMacAddr - find entry matching our MAC
reg_mac_oid="1.3.6.1.4.1.4491.2.1.20.1.3.1.2"
echo "Walking docsIf3CmtsCmRegStatusMacAddr to find CM reg ID..."
result=$(snmpwalk -v2c -c "$CMTS_COMMUNITY" -t $TIMEOUT -r $RETRIES -OXsq "$CMTS_IP" "$reg_mac_oid" 2>&1 | grep -i "${MODEM_MAC//:/ }" || echo "Not found")
echo "$result"
echo ""

total_end=$(date +%s.%N)
total_elapsed=$(echo "$total_end - $total_start" | bc)

echo "=============================================="
echo "TOTAL TIME: ${total_elapsed}s"
echo "=============================================="
