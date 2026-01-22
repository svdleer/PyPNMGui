#!/bin/bash
#
# Start UTSC FreeRun capture on E6000 CMTS with continuous re-triggering
# Interface: 1074405376
# Uses existing TFTP destination (DestinationIndex=1)
#
# The E6000 ignores RepeatPeriod and does 10 captures in ~200ms then stops.
# This script re-triggers every second to get continuous captures.
#

CMTS_IP="172.16.6.212"
COMMUNITY="Z1gg0Sp3c1@l"
RF_PORT="1074405376"
UTSC_CFG_BASE="1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
UTSC_CTRL_BASE="1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1"

# Configuration
TRIGGER_MODE=2              # 2 = FreeRunning
REPEAT_PERIOD_US=1000000    # 1 second in microseconds (ignored by E6000)
FREERUN_DURATION_MS=60000   # 60 seconds
TRIGGER_COUNT=10            # Max supported by E6000
FILENAME="/pnm/utsc/utsc_freerun"
DURATION_SECONDS=60         # How long to run

echo "================================================"
echo "UTSC FreeRun Continuous Capture - E6000"
echo "================================================"
echo "CMTS: $CMTS_IP"
echo "RF Port: $RF_PORT"
echo "Mode: FreeRunning with re-trigger every 1s"
echo "Duration: ${DURATION_SECONDS} seconds"
echo ""

# Step 1: Configure UTSC parameters
echo "Step 1: Configuring UTSC parameters..."

snmpset -v2c -c "$COMMUNITY" "$CMTS_IP" \
    "${UTSC_CFG_BASE}.3.${RF_PORT}.1" i $TRIGGER_MODE \
    "${UTSC_CFG_BASE}.12.${RF_PORT}.1" s "$FILENAME" \
    "${UTSC_CFG_BASE}.18.${RF_PORT}.1" u $REPEAT_PERIOD_US \
    "${UTSC_CFG_BASE}.19.${RF_PORT}.1" u $FREERUN_DURATION_MS \
    "${UTSC_CFG_BASE}.24.${RF_PORT}.1" u 1 \
    2>&1

if [ $? -ne 0 ]; then
    echo "Warning: Some parameters may not have been set (row may be locked)"
fi

# Step 2: Continuous triggering loop
echo ""
echo "Step 2: Starting continuous capture (Ctrl+C to stop)..."
echo ""

START_TIME=$(date +%s)
END_TIME=$((START_TIME + DURATION_SECONDS))
COUNT=0

while [ $(date +%s) -lt $END_TIME ]; do
    COUNT=$((COUNT + 1))
    ELAPSED=$(($(date +%s) - START_TIME))
    
    # Trigger the test
    snmpset -v2c -c "$COMMUNITY" "$CMTS_IP" \
        "${UTSC_CTRL_BASE}.1.${RF_PORT}.1" i 1 \
        >/dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        echo "[${ELAPSED}s] Trigger #${COUNT} sent ✓"
    else
        echo "[${ELAPSED}s] Trigger #${COUNT} failed ✗"
    fi
    
    # Wait 1 second before next trigger
    sleep 1
done

echo ""
echo "================================================"
echo "✅ Capture complete!"
echo "   Triggers sent: $COUNT"
echo "   Duration: ${DURATION_SECONDS} seconds"
echo "   Expected files: ~$((COUNT * 10)) (10 per trigger)"
echo ""
echo "Files in /var/lib/tftpboot/utsc_freerun_*"
echo "================================================"
