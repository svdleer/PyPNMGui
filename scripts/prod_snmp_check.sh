set -e
CMTS_IP=$(python3 -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/cmts', timeout=8)); items=d.get('cmts_list') or d.get('items') or []; print(next(((i.get('IPAddress') or i.get('ip') or '').strip() for i in items if (i.get('IPAddress') or i.get('ip'))), ''))")
echo "CMTS_IP=$CMTS_IP"
COMM=$(docker exec pypnm-api-prod /bin/sh -lc 'printenv CMTS_SNMP_COMMUNITY')
if [ -n "$COMM" ]; then
  echo "COMM_SET=yes"
  echo "COMM_LEN=${#COMM}"
else
  echo "COMM_SET=no"
fi
if [ -z "$CMTS_IP" ] || [ -z "$COMM" ]; then
  exit 0
fi
if ! command -v snmpget >/dev/null 2>&1; then
  echo "SNMPGET_NOT_INSTALLED"
  exit 0
fi
OUT=$(snmpget -v2c -c "$COMM" -t 2 -r 1 "$CMTS_IP" 1.3.6.1.2.1.1.1.0 2>&1 || true)
if echo "$OUT" | grep -qiE 'Timeout|No Response'; then
  echo "SNMP_RESULT=TIMEOUT"
elif echo "$OUT" | grep -qiE 'Authentication failure|authorizationError'; then
  echo "SNMP_RESULT=AUTH_FAILURE"
elif echo "$OUT" | grep -q 'STRING:'; then
  echo "SNMP_RESULT=OK"
else
  echo "SNMP_RESULT=UNKNOWN"
  echo "$OUT" | head -n 1
fi
