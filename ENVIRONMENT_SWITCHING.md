# PyPNMGui Environment Switching Guide

## Production vs LAB Environments

### Production Environment
- **Port**: 5050
- **Uses**: Remote agent via WebSocket
- **CMTS Access**: Via SSH tunnel through jump server
- **Tag**: `v1.0-production`
- **Config**: All CMTS systems in network

### LAB Environment  
- **Port**: 5051
- **Uses**: Direct SNMP access (no agent)
- **CMTS Access**: Direct network access
- **Config**: 4 CMTS systems only
- **Data**: Separate volumes (lab data isolated)

## Switching Between Environments

### Switch to Production
```bash
cd /opt/pypnm-gui/docker
docker-compose -f docker-compose.yml down
docker-compose -f docker-compose.yml up -d
```

Access: http://localhost:5050

### Switch to LAB
```bash
cd /opt/pypnm-gui/docker
docker-compose -f docker-compose.lab.yml down
docker-compose -f docker-compose.lab.yml up -d
```

Access: http://localhost:5051

### Run Both Simultaneously
Production on port 5050, LAB on port 5051:
```bash
cd /opt/pypnm-gui/docker

# Start production
docker-compose -f docker-compose.yml up -d

# Start lab
docker-compose -f docker-compose.lab.yml up -d
```

## Quick Switch Scripts

### switch-to-production.sh
```bash
#!/bin/bash
cd /opt/pypnm-gui/docker
docker-compose -f docker-compose.lab.yml down 2>/dev/null
docker-compose -f docker-compose.yml up -d
echo "Switched to PRODUCTION (port 5050)"
```

### switch-to-lab.sh
```bash
#!/bin/bash
cd /opt/pypnm-gui/docker
docker-compose -f docker-compose.yml down 2>/dev/null
docker-compose -f docker-compose.lab.yml up -d
echo "Switched to LAB (port 5051)"
```

## Checking Current Environment

```bash
docker ps | grep pypnm-gui
```

- `pypnm-gui` = Production
- `pypnm-gui-lab` = LAB

## Rollback to Production Version

```bash
cd /opt/pypnm-gui
git checkout v1.0-production
cd docker
docker-compose down
docker-compose up -d --build
```

## Data Isolation

- Production data: `pypnm-data` volume
- LAB data: `pypnm-data-lab` volume
- Redis production: port 6379
- Redis LAB: port 6380

Data is completely isolated between environments.
