# PyPNM Web GUI

A modern web-based graphical user interface for [PyPNM](https://github.com/svdleer/PyPNM) - the Proactive Network Maintenance toolkit for DOCSIS cable modems.

## Architecture

```
┌────────────────────────────────────┐
│  PyPNM Web GUI (This Project)      │
│  Flask on port 5050                │
│  - Modern Vue.js interface         │
│  - WebSocket agent management      │
│  - CMTS management                 │
└──────────────▲─────────────────────┘
               │ WebSocket
┌──────────────┴─────────────────────┐
│  PyPNM Agent (Separate Repo)       │
│  github.com/svdleer/pyPNMAgent     │
│  - SNMP operations via pysnmp      │
│  - Network access to CMTS/modems   │
│  - PNM measurements                │
└──────────────▲─────────────────────┘
               │ SNMP
       ┌───────┴───────┐
       │  CMTS/Modems  │
       └───────────────┘
```

## Components

| Component | Repository | Purpose |
|-----------|------------|---------|
| **PyPNM GUI** | This repo | Web interface + API server |
| **PyPNM Agent** | [github.com/svdleer/pyPNMAgent](https://github.com/svdleer/pyPNMAgent) | Remote SNMP agent |
| **PyPNM** | [github.com/svdleer/PyPNM](https://github.com/svdleer/PyPNM) | PNM library (required) |

## Prerequisites

1. **Python 3.10+** (or Docker)
2. **PyPNM Agent** deployed on a server with network access to CMTS/modems

## Quick Start
## Auth DB Init Script

Role-based login uses an auth database (MySQL or SQLite fallback). To initialize
tables and verify connectivity, run:

```bash
python backend/scripts/init_auth_db.py
```

Useful env vars:

- `AUTH_DB_BACKEND=mysql` (optional, auto-detected when `AUTH_DB_HOST` is set)
- `AUTH_DB_HOST`, `AUTH_DB_PORT`, `AUTH_DB_USER`, `AUTH_DB_PASSWORD`, `AUTH_DB_NAME`
- `AUTH_BOOTSTRAP_ADMIN_USER`, `AUTH_BOOTSTRAP_ADMIN_PASS`

The script prints `AUTH_DB_OK ...` with user/admin counts on success.


### Docker (Recommended)

```bash
# Clone both repos
git clone https://github.com/svdleer/PyPNMGui.git
git clone https://github.com/svdleer/pyPNMAgent.git

# Start GUI server
cd PyPNMGui
docker compose -f docker/docker-compose.yml up -d

# Configure and start agent (on jump server)
cd ../pyPNMAgent
cp agent_config.example.json config/agent_config.json
# Edit config/agent_config.json with your CMTS details
docker compose up -d
```

### Manual Installation

```bash
# 1. Start the GUI server
cd PyPNMGui
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
cd backend && python run.py

# 2. Start the agent (on jump server)
cd pyPNMAgent
pip install -r requirements.txt
cp agent_config.example.json agent_config.json
python agent.py -c agent_config.json
```

Open http://localhost:5050 in your browser.

## Features

- 🔍 **Cable Modem Search** - Search by IP, MAC, CMTS, or interface
- 📊 **Real-time Statistics** - View downstream/upstream channel stats via PyPNM
- 🔬 **PNM Measurements** - Run RxMER, Spectrum Analysis, Constellation Display
- 📋 **Event Log Viewer** - Browse modem event logs
- 📈 **Data Visualization** - Charts for RxMER and other measurements
- 🎨 **Modern UI** - Bootstrap 5 + Vue.js 3 + SweetAlert2
- 🔄 **PyPNM Integration** - Seamless proxy to PyPNM FastAPI

## Configuration

### Environment Variables

```bash
# PyPNM server URL (default: http://127.0.0.1:8000)
export PYPNM_BASE_URL=http://127.0.0.1:8000

# Flask server port (default: 5050)
export FLASK_PORT=5050

# Redis cache (optional, for CMTS data caching)
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_TTL=21600
```

### PyPNM Configuration

For PyPNM configuration (SNMP settings, TFTP servers, etc.), edit PyPNM's `system.json`:
```bash
cd PyPNM
nano src/pypnm/settings/system.json
```

See PyPNM repository: https://github.com/svdleer/PyPNM

## Project Structure

```
PyPNMGui/
├── backend/
│   ├── app/
│   │   ├── __init__.py          # Flask app factory
│   │   ├── core/
│   │   │   ├── config.py        # Configuration settings
│   │   │   ├── simple_ws.py     # WebSocket agent manager
│   │   │   └── cmts_provider.py # CMTS list provider
│   │   └── routes/
│   │       ├── main_routes.py   # Frontend serving
│   │       └── api_routes.py    # API endpoints
│   ├── run.py                   # Entry point
│   └── requirements.txt         # Python dependencies
├── frontend/
│   ├── templates/
│   │   └── index.html           # Main HTML template
│   └── static/
│       ├── css/
│       │   └── style.css        # Custom styles
│       └── js/
│           └── app.js           # Vue.js application
├── docker/
│   ├── docker-compose.yml       # Docker deployment
│   └── Dockerfile               # GUI server image
├── deploy/
│   └── lab-deploy.sh            # Lab deployment script
├── docs/
│   └── ...                      # Documentation
└── README.md                    # This file
```

## Agent Setup

The PyPNM Agent runs on a jump server with network access to your DOCSIS equipment.

See: **[github.com/svdleer/pyPNMAgent](https://github.com/svdleer/pyPNMAgent)**

```bash
# On your jump server
git clone https://github.com/svdleer/pyPNMAgent.git
cd pyPNMAgent
cp agent_config.example.json agent_config.json
# Edit agent_config.json with:
#   - pypnm_server.url: ws://your-gui-server:5050/ws/agent
#   - cmts_access.community: your-cmts-snmp-community
docker compose up -d
```

## API Endpoints

This Web GUI proxies requests to PyPNM's FastAPI endpoints. All data comes from PyPNM.

### Web GUI Endpoints (proxy layer)

| Endpoint | Method | Description | PyPNM Target |
|----------|--------|-------------|--------------|
| `/api/health` | GET | Check PyPNM connectivity | - |
| `/api/modem/<mac>/system-info` | POST | Get sysDescr | `/system/sysDescr` |
| `/api/modem/<mac>/uptime` | POST | Get uptime | `/system/upTime` |
| `/api/modem/<mac>/event-log` | POST | Get event log | `/docs/dev/eventLog` |
| `/api/modem/<mac>/ds-channels` | POST | Downstream stats | `/docs/if30/ds/*` + `/docs/if31/ds/*` |
| `/api/modem/<mac>/us-channels` | POST | Upstream stats | `/docs/if30/us/*` + `/docs/if31/us/*` |
| `/api/modem/<mac>/rxmer` | POST | RxMER measurement | `/docs/pnm/ds/ofdm/rxmer/getCapture` |
| `/api/modem/<mac>/spectrum` | POST | Spectrum analysis | `/docs/pnm/spectrumAnalyzer/getCapture` |
| `/api/modem/<mac>/constellation` | POST | Constellation | `/docs/pnm/ds/ofdm/const_display/getCapture` |

### PyPNM Direct Endpoints

For complete API documentation, see PyPNM's Swagger UI at: **http://127.0.0.1:8000/docs**

### Request Format

Example POST request to Web GUI:
```bash
curl -X POST http://localhost:5050/api/modem/aa:bb:cc:dd:ee:ff/system-info \
  -H "Content-Type: application/json" \
  -d '{
    "modem_ip": "192.168.100.10",
    "community": "private"
  }'
```

This is proxied to PyPNM as:
```bash
curl -X POST http://127.0.0.1:8000/system/sysDescr \
  -H "Content-Type: application/json" \
  -d '{
    "cable_modem": {
      "mac_address": "aa:bb:cc:dd:ee:ff",
      "ip_address": "192.168.100.10",
      "snmp": {
        "snmpV2C": {
          "community": "private"
        }
      }
    }
  }'
```

## Remote Agent (Optional)

If PyPNM cannot directly reach cable modems (firewall, network segmentation), you can deploy a remote agent on a Jump Server. See:

- [github.com/svdleer/pyPNMAgent](https://github.com/svdleer/pyPNMAgent) - Agent deployment guide
- [docs/PYPNM_INTEGRATION.md](docs/PYPNM_INTEGRATION.md) - Detailed architecture

## Troubleshooting

### PyPNM Not Reachable

**Error:** `PyPNM server not reachable at http://127.0.0.1:8000`

**Solution:**
1. Verify PyPNM is running: `curl http://127.0.0.1:8000/docs`
2. Check PyPNM logs: `cd PyPNM && tail -f logs/pypnm.log`
3. Start PyPNM if not running: `cd PyPNM && source venv/bin/activate && pypnm`

### TFTP Required for PNM Measurements

**Error:** `tftp_ipv4 required for PNM measurements`

**Reason:** PNM measurements (RxMER, Spectrum, etc.) require the cable modem to upload capture files to a TFTP server.

**Solution:**
1. Configure TFTP in PyPNM's `system.json`
2. Ensure TFTP server is reachable from cable modems
3. See: https://github.com/svdleer/PyPNM/blob/main/docs/install/install.md

### No Modems Found

This Web GUI does not query modems from CMTS directly. You need to either:
1. Use PyPNM's Python library to query CMTS
2. Maintain a separate database of modems
3. Search by specific MAC/IP address

## Development

### Running in Development Mode

```bash
# Terminal 1: PyPNM server
cd PyPNM
source venv/bin/activate
pypnm

# Terminal 2: Web GUI
cd PyPNMGui
source venv/bin/activate
export FLASK_DEBUG=1
cd backend
python run.py
```

### Adding New Features

1. Check PyPNM API docs: http://127.0.0.1:8000/docs
2. Add proxy endpoint in `backend/app/routes/api_routes.py`
3. Add method to `backend/app/core/pypnm_client.py`
4. Update frontend in `frontend/static/js/app.js`

## Resources

- **PyPNM GitHub:** https://github.com/svdleer/PyPNM
- **PyPNM API Reference:** http://localhost:8000/docs (after install)
- **Integration Plan:** [docs/PYPNM_INTEGRATION.md](docs/PYPNM_INTEGRATION.md)
- **Network Architecture:** [docs/NETWORK_ARCHITECTURE.md](docs/NETWORK_ARCHITECTURE.md)

## Contributing

This project provides a Web GUI for PyPNM. For PyPNM core features (SNMP, PNM measurements, etc.), contribute to the main PyPNM project.

For Web GUI improvements:
1. Fork this repository
2. Create a feature branch
3. Test with PyPNM
4. Submit a pull request

## License

Apache-2.0

## Support

- Web GUI Issues: Create an issue in this repository
- PyPNM Issues: https://github.com/svdleer/PyPNM/issues
