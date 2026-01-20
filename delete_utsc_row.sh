#!/bin/bash
# Delete UTSC configuration row on Casa E6000 CMTS
# This is required because the CMTS locks active rows and won't allow modification or deletion
# You must stop the UTSC capture first, then delete the row

CMTS_IP="172.16.6.212"
RF_PORT="1074339840"
COMMUNITY="Z1gg0Sp3c1@l"
ROW_STATUS_OID="1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.21.${RF_PORT}.1"

echo "==========================================="
echo "UTSC Row Deletion for Casa E6000 CMTS"
echo "==========================================="
echo "CMTS: $CMTS_IP"
echo "RF Port: $RF_PORT"
echo ""

echo "Step 1: Checking current row status..."
ssh -p 65001 access-engineering.nl "docker exec pypnm-agent-lab snmpget -v2c -Ov -c '$COMMUNITY' $CMTS_IP $ROW_STATUS_OID 2>&1 | tail -3"

echo ""
echo "Step 2: Attempting to delete row (RowStatus=6 destroy)..."
ssh -p 65001 access-engineering.nl "docker exec pypnm-agent-lab snmpset -v2c -c '$COMMUNITY' $CMTS_IP $ROW_STATUS_OID i 6 2>&1 | grep -v 'Cannot adopt' | tail -5"

echo ""
echo "Step 3: Verifying deletion..."
ssh -p 65001 access-engineering.nl "docker exec pypnm-agent-lab snmpget -v2c -Ov -c '$COMMUNITY' $CMTS_IP $ROW_STATUS_OID 2>&1 | tail -3"

echo ""
echo "==========================================="
echo "If deletion failed with 'inconsistentValue',"
echo "the row is locked and cannot be deleted while"
echo "UTSC is active. Stop UTSC first or restart CMTS."
echo "==========================================="
