#!/bin/bash
# PyPNMGui + API production install script
# Usage: sudo ./install_pypnm_prod.sh
set -e

# 1. Prompt for config
read -p "Agent token: " AGENT_TOKEN
read -p "SNMP community (ARRIS): " SNMP_COMMUNITY_ARRIS
read -p "SNMP community (CASA): " SNMP_COMMUNITY_CASA
read -p "SNMP community (CISCO): " SNMP_COMMUNITY_CISCO
read -p "SNMP community (COMMSCOPE): " SNMP_COMMUNITY_COMMSCOPE
read -p "Modem SNMP community: " CM_DIRECT_COMMUNITY
read -p "TFTP IPv4 (default 172.16.6.101): " TFTP_IPV4
TFTP_IPV4=${TFTP_IPV4:-172.16.6.101}
read -p "TFTP IPv4 ALT (default 172.22.147.18): " TFTP_IPV4_ALT
TFTP_IPV4_ALT=${TFTP_IPV4_ALT:-172.22.147.18}

# 2. Write .env file
cat > .env.prod <<EOF
PYPNM_AGENT_TOKEN=$AGENT_TOKEN
SNMP_COMMUNITY_ARRIS=$SNMP_COMMUNITY_ARRIS
SNMP_COMMUNITY_CASA=$SNMP_COMMUNITY_CASA
SNMP_COMMUNITY_CISCO=$SNMP_COMMUNITY_CISCO
SNMP_COMMUNITY_COMMSCOPE=$SNMP_COMMUNITY_COMMSCOPE
CM_DIRECT_COMMUNITY=$CM_DIRECT_COMMUNITY
TFTP_IPV4=$TFTP_IPV4
TFTP_IPV4_ALT=$TFTP_IPV4_ALT
EOF

# 3. Build and start Docker containers
cp docker/docker-compose.lab.yml docker-compose.prod.yml
sed -i '' 's/\.env/\.env.prod/g' docker-compose.prod.yml

echo "[INFO] Building and starting PyPNMGui + API + Redis..."
docker compose -f docker-compose.prod.yml up -d --build

echo "[INFO] Waiting for services to start..."
sleep 10

echo "[INFO] PyPNMGui: http://localhost:5050"
echo "[INFO] PyPNM API: http://localhost:8000/docs"
echo "[INFO] Redis: localhost:6379"
